# monkeyplug

[![Latest Version](https://img.shields.io/pypi/v/monkeyplug)](https://pypi.python.org/pypi/monkeyplug/) [![VOSK Docker Images](https://github.com/mmguero/monkeyplug/workflows/monkeyplug-build-push-vosk-ghcr/badge.svg)](https://github.com/mmguero/monkeyplug/pkgs/container/monkeyplug) [![Whisper Docker Images](https://github.com/mmguero/monkeyplug/workflows/monkeyplug-build-push-whisper-ghcr/badge.svg)](https://github.com/mmguero/monkeyplug/pkgs/container/monkeyplug)

**monkeyplug** is a little script to censor profanity in audio files (intended for podcasts, but YMMV) in a few simple steps:

1. The user provides a local audio file (or a URL pointing to an audio file which is downloaded)
2. Either [Whisper](https://openai.com/research/whisper) ([GitHub](https://github.com/openai/whisper)) or the [Vosk](https://alphacephei.com/vosk/)-[API](https://github.com/alphacep/vosk-api) is used to recognize speech in the audio file (or a pre-generated transcript can be loaded)
3. Each recognized word is checked against a [list](./src/monkeyplug/swears.txt) of profanity or other words you'd like muted
4. [`ffmpeg`](https://www.ffmpeg.org/) is used to create a cleaned audio file, muting or "bleeping" the objectional words
5. Optionally, the transcript can be saved for reuse in future processing runs

You can then use your favorite media player to play the cleaned audio file.

If provided a video file for input, **monkeyplug** will attempt to process the audio stream from the file and remultiplex it, copying the original video stream. 

**monkeyplug** is part of a family of projects with similar goals:

* 📼 [cleanvid](https://github.com/mmguero/cleanvid) for video files (using [SRT-formatted](https://en.wikipedia.org/wiki/SubRip#Format) subtitles)
* 🎤 [monkeyplug](https://github.com/mmguero/monkeyplug) for audio and video files (using either [Whisper](https://openai.com/research/whisper) or the [Vosk](https://alphacephei.com/vosk/)-[API](https://github.com/alphacep/vosk-api) for speech recognition)
* 📕 [montag](https://github.com/mmguero/montag) for ebooks

## Installation

Using `pip`, to install the latest [release from PyPI](https://pypi.org/project/monkeyplug/):

```
python3 -m pip install -U monkeyplug
```

Or to install directly from GitHub:


```
python3 -m pip install -U 'git+https://github.com/mmguero/monkeyplug'
```

## Prerequisites

[monkeyplug](./src/monkeyplug/monkeyplug.py) requires:

* [FFmpeg](https://www.ffmpeg.org)
* Python 3
    - [mutagen](https://github.com/quodlibet/mutagen)
    - a speech recognition library, either of:
        + [Whisper](https://github.com/openai/whisper)
        + [vosk-api](https://github.com/alphacep/vosk-api) with a VOSK [compatible model](https://alphacephei.com/vosk/models)

To install FFmpeg, use your operating system's package manager or install binaries from [ffmpeg.org](https://www.ffmpeg.org/download.html). The Python dependencies will be installed automatically if you are using `pip` to install monkeyplug, except for [`vosk`](https://pypi.org/project/vosk/) or [`openai-whisper`](https://pypi.org/project/openai-whisper/); as monkeyplug can work with both speech recognition engines, there is not a hard installation requirement for either until runtime.

## usage

```
usage: monkeyplug <arguments>

options:
  -h, --help            show this help message and exit
  -v [true|false], --verbose [true|false]
                        Verbose/debug output
  -m <string>, --mode <string>
                        Speech recognition engine (whisper|vosk) (default: whisper)
  -i <string>, --input <string>
                        Input file (or URL)
  -o <string>, --output <string>
                        Output file
  -w <profanity file>, --swears <profanity file>
                        text file containing profanity (default: "swears.txt")
  --output-json <string>
                        Output file to store transcript JSON
  --input-transcript <string>
                        Load existing transcript JSON instead of performing speech recognition
  --save-transcript     Automatically save transcript JSON alongside output audio file
  --force-retranscribe  Force new transcription even if transcript file exists (overrides automatic reuse)
  -a <str>, --audio-params <str>
                        Audio parameters for ffmpeg (default depends on output audio codec)
  -c <int>, --channels <int>
                        Audio output channels (default: 2)
  -s <int>, --sample-rate <int>
                        Audio output sample rate (default: 48000)
  -r <str>, --bitrate <str>
                        Audio output bitrate (default: 256K)
  -q <int>, --vorbis-qscale <int>
                        qscale for libvorbis output (default: 5)
  -f <string>, --format <string>
                        Output file format (default: inferred from extension of --output, or "MATCH")
  --pad-milliseconds <int>
                        Milliseconds to pad on either side of muted segments (default: 0)
  --pad-milliseconds-pre <int>
                        Milliseconds to pad before muted segments (default: 0)
  --pad-milliseconds-post <int>
                        Milliseconds to pad after muted segments (default: 0)
  -b [true|false], --beep [true|false]
                        Beep instead of silence
  -z <int>, --beep-hertz <int>
                        Beep frequency hertz (default: 1000)
  --beep-mix-normalize [true|false]
                        Normalize mix of audio and beeps (default: False)
  --beep-audio-weight <int>
                        Mix weight for non-beeped audio (default: 1)
  --beep-sine-weight <int>
                        Mix weight for beep (default: 1)
  --beep-dropout-transition <int>
                        Dropout transition for beep (default: 0)
  --force [true|false]  Process file despite existence of embedded tag

VOSK Options:
  --vosk-model-dir <string>
                        VOSK model directory (default: ~/.cache/vosk)
  --vosk-read-frames-chunk <int>
                        WAV frame chunk (default: 8000)

Whisper Options:
  --whisper-model-dir <string>
                        Whisper model directory (~/.cache/whisper)
  --whisper-model-name <string>
                        Whisper model name (base.en)
  --torch-threads <int>
                        Number of threads used by torch for CPU inference (0)

```

### Docker

Alternately, a [Dockerfile](./docker/Dockerfile) is provided to allow you to run monkeyplug in Docker. You can pull one of the following images:

* [VOSK](https://alphacephei.com/vosk/models)
    - oci.guero.org/monkeyplug:vosk-small
    - oci.guero.org/monkeyplug:vosk-large
* [Whisper](https://github.com/openai/whisper?tab=readme-ov-file#available-models-and-languages)
    - oci.guero.org/monkeyplug:whisper-tiny.en
    - oci.guero.org/monkeyplug:whisper-tiny
    - oci.guero.org/monkeyplug:whisper-base.en
    - oci.guero.org/monkeyplug:whisper-base
    - oci.guero.org/monkeyplug:whisper-small.en
    - oci.guero.org/monkeyplug:whisper-small
    - oci.guero.org/monkeyplug:whisper-medium.en
    - oci.guero.org/monkeyplug:whisper-medium
    - oci.guero.org/monkeyplug:whisper-large-v1
    - oci.guero.org/monkeyplug:whisper-large-v2
    - oci.guero.org/monkeyplug:whisper-large-v3
    - oci.guero.org/monkeyplug:whisper-large

then run [`monkeyplug-docker.sh`](./docker/monkeyplug-docker.sh) inside the directory where your audio files are located.

## Transcript Workflow

**monkeyplug** supports saving and reusing transcripts to improve workflow efficiency:

### Save Transcript for Later Reuse

```bash
# Generate transcript once and save it
monkeyplug -i input.mp3 -o output.mp3 --save-transcript

# This creates output.mp3 and output_transcript.json
```

### Automatic Transcript Reuse

```bash
# Second run: Automatically detects and reuses transcript (22x faster!)
monkeyplug -i input.mp3 -o output.mp3 --save-transcript
# Finds output_transcript.json and reuses it automatically

# Force new transcription when needed
monkeyplug -i input.mp3 -o output.mp3 --save-transcript --force-retranscribe
```

### Manual Transcript Loading

```bash
# Explicitly specify transcript to load
monkeyplug -i input.mp3 -o output_strict.mp3 --input-transcript output_transcript.json -w strict_swears.txt
```

## Contributing

If you'd like to help improve monkeyplug, pull requests will be welcomed!

## Authors

* **Seth Grover** - *Initial work* - [mmguero](https://github.com/mmguero)

## License

This project is licensed under the BSD 3-Clause License - see the [LICENSE](LICENSE) file for details.
