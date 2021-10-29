# monkeyplug

monkeyplug is a little script to mute profanity in audio files (intended for podcasts, but YMMV) in a few simple steps:

1. The user provides a local audio file (or a URL pointing to an audio file which is downloaded)
2. The [Vosk](https://alphacephei.com/vosk/)-[API](https://github.com/alphacep/vosk-api) is used to recognize speech in the audio file
3. Each recognized word is checked against a [list](swears.txt) of profanity or other words you'd like muted
4. [`ffmpeg`](https://www.ffmpeg.org/) is used to create a cleaned audio file, muting the objectional words

You can then use your favorite media player to play the cleaned audio file.

## Prerequisites

[monkeyplug](monkeyplug.py) requires:

* [FFmpeg](https://www.ffmpeg.org)
* Python 3
    - [delegator.py](https://github.com/kennethreitz/delegator.py)
    - [vosk-api](https://github.com/alphacep/vosk-api) Python bindings
+ A Vosk-API [compatible model](https://alphacephei.com/vosk/models) in a subdirectory named `model` in the same directory as `monkeyplug.py`

## usage

```
$ ./monkeyplug.py --help
usage: monkeyplug.py <arguments>

monkeyplug.py

options:
  -v [true|false], --verbose [true|false]
                        Verbose/debug output
  -i <string>, --input <string>
                        Input audio file (or URL)
  -o <string>, --output <string>
                        Output audio file
  -w <profanity file>, --swears <profanity file>
                        text file containing profanity
  -a APARAMS, --audio-params APARAMS
                        Audio parameters for ffmpeg
  -x <string>, --extension <string>
                        Output audio file extension
  -m <string>, --model <string>
                        Vosk model path
  -f <int>, --frames <int>
                        WAV frame chunk
```

### Docker

Alternately, a [Dockerfile](Dockerfile) is provided to allow you to run monkeyplug in Docker. You can pull either the `ghcr.io/mmguero/monkeyplug:small` or `ghcr.io/mmguero/monkeyplug:large` Docker images, or build with [`build_docker.sh`](build_docker.sh), then run [`monkeyplug-docker.sh`](monkeyplug-docker.sh) inside the directory where your audio files are located.

## Contributing

If you'd like to help improve monkeyplug, pull requests will be welcomed!

## Authors

* **Seth Grover** - *Initial work* - [mmguero](https://github.com/mmguero)

## License

This project is licensed under the BSD 3-Clause License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

Thanks to:

* the developers of [FFmpeg](https://www.ffmpeg.org/about.html)
* [Mattias Wadman](https://github.com/wader) for his [ffmpeg](https://github.com/wader/static-ffmpeg) image
* [delegator.py](https://github.com/kennethreitz/delegator.py) developer Kenneth Reitz and contributors
* [Vosk](https://alphacephei.com/vosk/) and [vosk-api](https://github.com/alphacep/vosk-api) developers and contributors
