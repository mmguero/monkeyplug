########################################################################################################################
FROM python:3-slim as base

ENV DEBIAN_FRONTEND noninteractive
ENV TERM xterm
ENV PYTHONUNBUFFERED 1

ADD . /usr/local/src/monkeyplug

RUN apt-get update -q && \
    apt-get -y install -qq --no-install-recommends libarchive-tools curl && \
    python3 -m ensurepip && \
    python3 -m pip install --no-cache /usr/local/src/monkeyplug && \
    apt-get clean && \
      rm -rf /var/cache/apt/* /var/lib/apt/lists/* /tmp/* /var/tmp/* /usr/local/src/monkeyplug

COPY --from=mwader/static-ffmpeg:latest /ffmpeg /usr/local/bin/
COPY --from=mwader/static-ffmpeg:latest /ffprobe /usr/local/bin/

WORKDIR /tmp

ENTRYPOINT ["monkeyplug"]
CMD []

########################################################################################################################
FROM base as vosk

LABEL maintainer="mero.mero.guero@gmail.com"
LABEL org.opencontainers.image.authors='mero.mero.guero@gmail.com'
LABEL org.opencontainers.image.url='https://github.com/mmguero/monkeyplug'
LABEL org.opencontainers.image.source='https://github.com/mmguero/monkeyplug'
LABEL org.opencontainers.image.title='mmguero/monkeyplug'
LABEL org.opencontainers.image.description='Dockerized monkeyplug (VOSK-based)'

ENV MONKEYPLUG_MODE vosk
ENV VOSK_MODEL_DIR /opt/vosk_model

# see https://alphacephei.com/vosk/models
# use "vosk-model-en-us-0.22" if you want more accurate recognition (and a large image)
ARG VOSK_MODEL_URL="https://alphacephei.com/kaldi/models/vosk-model-small-en-us-0.15.zip"

RUN python3 -m pip install --no-cache vosk && \
    mkdir -p "$VOSK_MODEL_DIR" && \
    cd "$VOSK_MODEL_DIR" && \
    echo "Downloading Vosk model \"$VOSK_MODEL_URL\"..." && \
    curl -fsSL -o ./model.zip "$VOSK_MODEL_URL" && \
    bsdtar -xf ./model.zip -s'|[^/]*/||' && \
    echo "Finished" && \
    rm -f ./model.zip

########################################################################################################################
FROM base as whisper

LABEL maintainer="mero.mero.guero@gmail.com"
LABEL org.opencontainers.image.authors='mero.mero.guero@gmail.com'
LABEL org.opencontainers.image.url='https://github.com/mmguero/monkeyplug'
LABEL org.opencontainers.image.source='https://github.com/mmguero/monkeyplug'
LABEL org.opencontainers.image.title='mmguero/monkeyplug'
LABEL org.opencontainers.image.description='Dockerized monkeyplug (Whisper-based)'

ENV MONKEYPLUG_MODE whisper
ENV WHISPER_MODEL_DIR /opt/whisper_model

# see https://github.com/openai/whisper?tab=readme-ov-file#available-models-and-languages
ARG WHISPER_MODEL_NAME="small.en"
ENV WHISPER_MODEL_NAME $WHISPER_MODEL_NAME

RUN python3 -m pip install --no-cache openai-whisper && \
    mkdir -p "$WHISPER_MODEL_DIR" && \
    cd "$WHISPER_MODEL_DIR" && \
    echo "Downloading Whisper model \"$WHISPER_MODEL_NAME\"..." && \
    curl -fsSL -o ./"$WHISPER_MODEL_NAME".pt "$(curl -fsSL https://raw.githubusercontent.com/openai/whisper/main/whisper/__init__.py | grep -P "\"$WHISPER_MODEL_NAME\"\s*:\s*\"https://" | cut -d: -f2- | sed 's/^[[:space:]]*"//' | sed 's/",*$//')" && \
    echo "Finished"
