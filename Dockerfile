FROM python:3-slim

LABEL maintainer="mero.mero.guero@gmail.com"
LABEL org.opencontainers.image.authors='mero.mero.guero@gmail.com'
LABEL org.opencontainers.image.url='https://github.com/mmguero/monkeyplug'
LABEL org.opencontainers.image.source='https://github.com/mmguero/monkeyplug'
LABEL org.opencontainers.image.title='mmguero/monkeyplug'
LABEL org.opencontainers.image.description='Dockerized monkeyplug'

# see https://alphacephei.com/vosk/models
# use "vosk-model-en-us-0.22" if you want more accurate recognition (and a large image)
ARG VOSK_MODEL_URL="https://alphacephei.com/kaldi/models/vosk-model-small-en-us-0.15.zip"

ADD $VOSK_MODEL_URL /usr/local/bin/model/model.zip
ADD requirements.txt /tmp/requirements.txt

ENV DEBIAN_FRONTEND noninteractive
ENV TERM xterm
ENV PYTHONUNBUFFERED 1

RUN apt-get update -q && \
    apt-get -y install -qq --no-install-recommends libarchive-tools && \
    python3 -m ensurepip && \
    python3 -m pip install --no-cache --upgrade -r /tmp/requirements.txt && \
    cd /usr/local/bin/model && \
    bsdtar -xf model.zip -s'|[^/]*/||' && \
    cd / && \
    apt-get clean && \
      rm -rf /var/cache/apt/* /var/lib/apt/lists/* /tmp/* /var/tmp/* /usr/local/bin/model/model.zip

ADD *.py /usr/local/bin/
ADD swears.txt /usr/local/bin

WORKDIR /tmp

ENTRYPOINT ["python3", "/usr/local/bin/monkeyplug.py"]
CMD []
