#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import base64
import errno
import importlib.metadata
import json
import os
import shlex
import shutil
import string
import sys
import tempfile
import wave
from contextlib import contextmanager
from itertools import tee
from pathlib import Path
from urllib.parse import urlparse

import mmguero
import mutagen
import requests

###################################################################################################
CHANNELS_REPLACER = 'CHANNELS'
SAMPLE_RATE_REPLACER = 'SAMPLE'
BIT_RATE_REPLACER = 'BITRATE'
VORBIS_QSCALE_REPLACER = 'QSCALE'
AUDIO_DEFAULT_PARAMS_BY_FORMAT = {
    "flac": ["-c:a", "flac", "-ar", SAMPLE_RATE_REPLACER, "-ac", CHANNELS_REPLACER],
    "m4a": ["-c:a", "aac", "-b:a", BIT_RATE_REPLACER, "-ar", SAMPLE_RATE_REPLACER, "-ac", CHANNELS_REPLACER],
    "aac": ["-c:a", "aac", "-b:a", BIT_RATE_REPLACER, "-ar", SAMPLE_RATE_REPLACER, "-ac", CHANNELS_REPLACER],
    "mp3": ["-c:a", "libmp3lame", "-b:a", BIT_RATE_REPLACER, "-ar", SAMPLE_RATE_REPLACER, "-ac", CHANNELS_REPLACER],
    "ogg": [
        "-c:a",
        "libvorbis",
        "-qscale:a",
        VORBIS_QSCALE_REPLACER,
        "-ar",
        SAMPLE_RATE_REPLACER,
        "-ac",
        CHANNELS_REPLACER,
    ],
    "opus": ["-c:a", "libopus", "-b:a", BIT_RATE_REPLACER, "-ar", SAMPLE_RATE_REPLACER, "-ac", CHANNELS_REPLACER],
    "ac3": ["-c:a", "ac3", "-b:a", BIT_RATE_REPLACER, "-ar", SAMPLE_RATE_REPLACER, "-ac", CHANNELS_REPLACER],
    "wav": ["-c:a", "pcm_s16le", "-ar", SAMPLE_RATE_REPLACER, "-ac", CHANNELS_REPLACER],
}
AUDIO_CODEC_TO_FORMAT = {
    "aac": "m4a",
    "ac3": "ac3",
    "flac": "flac",
    "mp3": "mp3",
    "opus": "opus",
    "vorbis": "ogg",
    "pcm_s16le": "wav",
}

AUDIO_DEFAULT_CHANNELS = 2
AUDIO_DEFAULT_SAMPLE_RATE = 48000
AUDIO_DEFAULT_BIT_RATE = "256K"
AUDIO_DEFAULT_VORBIS_QSCALE = 5
AUDIO_MATCH_FORMAT = "MATCH"
AUDIO_INTERMEDIATE_PARAMS = ["-c:a", "pcm_s16le", "-ac", "1", "-ar", "16000"]
AUDIO_DEFAULT_WAV_FRAMES_CHUNK = 8000
BEEP_HERTZ_DEFAULT = 1000
BEEP_MIX_NORMALIZE_DEFAULT = False
BEEP_AUDIO_WEIGHT_DEFAULT = 1
BEEP_SINE_WEIGHT_DEFAULT = 1
BEEP_DROPOUT_TRANSITION_DEFAULT = 0
SWEARS_FILENAME_DEFAULT = 'swears.txt'
MUTAGEN_METADATA_TAGS = ['encodedby', 'comment']
MUTAGEN_METADATA_TAG_VALUE = u'monkeyplug'
SPEECH_REC_MODE_VOSK = "vosk"
SPEECH_REC_MODE_WHISPER = "whisper"
DEFAULT_SPEECH_REC_MODE = os.getenv("MONKEYPLUG_MODE", SPEECH_REC_MODE_WHISPER)
DEFAULT_VOSK_MODEL_DIR = os.getenv("VOSK_MODEL_DIR", str(Path.home() / ".cache" / "vosk"))
DEFAULT_WHISPER_MODEL_DIR = os.getenv("WHISPER_MODEL_DIR", str(Path.home() / ".cache" / "whisper"))
DEFAULT_WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL_NAME", "small.en")
DEFAULT_TORCH_THREADS = 0

###################################################################################################
script_file = Path(__file__).resolve()
script_name = script_file.name
script_path = str(script_file.parent)


# thanks https://docs.python.org/3/library/itertools.html#recipes
def pairwise(iterable):
    a, b = tee(iterable)
    next(b, None)
    return zip(a, b)


def scrubword(value):
    return str(value).lower().replace("’", "'").strip().strip(string.punctuation)


def _safe_unlink(file_spec):
    if file_spec:
        try:
            Path(file_spec).unlink(missing_ok=True)
        except OSError:
            pass


def _process_output_tail(output, max_lines=20):
    if isinstance(output, (list, tuple)):
        lines = [str(line) for line in mmguero.flatten(output)]
    else:
        lines = str(output).splitlines()
    return "\n".join(lines[-max_lines:])


def _raise_process_error(action, command, result, output):
    command_text = shlex.join([str(arg) for arg in mmguero.flatten(command)])
    output_tail = _process_output_tail(output)
    mmguero.eprint(command_text)
    mmguero.eprint(result)
    if output_tail:
        mmguero.eprint(output_tail)
    detail = f"\n{output_tail}" if output_tail else ""
    raise RuntimeError(f"{action} (ffmpeg/ffprobe exit code {result}){detail}")


@contextmanager
def _temporary_output_path(final_path):
    final_path = Path(final_path)
    parent = final_path.parent if str(final_path.parent) else Path.cwd()
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.monkeyplug_', dir=str(parent)) as tmp_dir:
        yield str(Path(tmp_dir) / final_path.name)


def _write_json_atomic(file_spec, value):
    destination = Path(file_spec)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode='w',
        encoding='utf-8',
        dir=str(destination.parent),
        prefix=f'.{destination.name}.',
        suffix='.tmp',
        delete=False,
    ) as tmp_file:
        tmp_path = Path(tmp_file.name)
        json.dump(value, tmp_file)
    try:
        os.replace(tmp_path, destination)
    finally:
        _safe_unlink(tmp_path)


###################################################################################################
# download to file
def DownloadToFile(url, local_filename=None, chunk_bytes=4096, debug=False):
    parsed_path = Path(urlparse(url).path)
    if local_filename:
        destination = Path(local_filename)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.NamedTemporaryFile(
            mode='wb',
            dir=str(destination.parent),
            prefix=f'.{destination.name}.',
            suffix='.part',
            delete=False,
        )
    else:
        suffix = parsed_path.suffix
        temporary = tempfile.NamedTemporaryFile(
            mode='wb',
            prefix='monkeyplug_download_',
            suffix=suffix,
            delete=False,
        )
        destination = Path(temporary.name)

    temporary_path = Path(temporary.name)
    try:
        with temporary as file_handle, requests.get(
            url,
            stream=True,
            allow_redirects=True,
            timeout=(10, 60),
        ) as response:
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=chunk_bytes):
                if chunk:
                    file_handle.write(chunk)

        file_size = temporary_path.stat().st_size
        if file_size <= 0:
            _safe_unlink(temporary_path)
            return None

        if local_filename:
            os.replace(temporary_path, destination)
        else:
            destination = temporary_path

        if debug:
            mmguero.eprint(
                f"Download of {url} to {destination} succeeded "
                f"({mmguero.size_human_format(file_size)})"
            )
        return str(destination)
    except Exception:
        _safe_unlink(temporary_path)
        raise


###################################################################################################
# Get tag from file to indicate monkeyplug has already been set
def GetMonkeyplugTagged(local_filename, debug=False):
    if not Path(local_filename).is_file():
        return False

    mut = mutagen.File(local_filename, easy=True)
    if debug:
        mmguero.eprint(f'Tags of {local_filename}: {mut}')
    if not hasattr(mut, 'get'):
        return False

    expected_errors = (KeyError, TypeError, ValueError, OSError, mutagen.MutagenError)
    for tag in MUTAGEN_METADATA_TAGS:
        try:
            if MUTAGEN_METADATA_TAG_VALUE in mmguero.get_iterable(mut.get(tag, default=())):
                return True
        except expected_errors as exc:
            if debug:
                mmguero.eprint(exc)
    return False


###################################################################################################
# Set tag to file to indicate monkeyplug has worked its magic
def SetMonkeyplugTag(local_filename, debug=False):
    if not Path(local_filename).is_file():
        return False

    mut = mutagen.File(local_filename, easy=True)
    if debug:
        mmguero.eprint(f'Tags of {local_filename} before: {mut}')
    if not hasattr(mut, '__setitem__'):
        return False

    expected_errors = (KeyError, TypeError, ValueError, OSError, mutagen.MutagenError)
    tag_set = False
    for tag in MUTAGEN_METADATA_TAGS:
        try:
            mut[tag] = MUTAGEN_METADATA_TAG_VALUE
            tag_set = True
            break
        except expected_errors as exc:
            if debug:
                mmguero.eprint(exc)

    if tag_set:
        try:
            mut.save(local_filename)
        except expected_errors as exc:
            tag_set = False
            mmguero.eprint(exc)

    if debug:
        mmguero.eprint(f'Tags of {local_filename} after: {mut}')
    return tag_set


###################################################################################################
# get stream codecs from an input filename
# e.g. result: {'video': {'h264'}, 'audio': {'eac3'}, 'subtitle': {'subrip'}}
def GetCodecs(local_filename, debug=False):
    if not Path(local_filename).is_file():
        return {}

    ffprobe_cmd = [
        'ffprobe',
        '-v',
        'quiet',
        '-print_format',
        'json',
        '-show_format',
        '-show_streams',
        local_filename,
    ]
    ffprobe_result, ffprobe_output = mmguero.run_process(
        ffprobe_cmd, stdout=True, stderr=True, debug=debug
    )
    if ffprobe_result != 0:
        _raise_process_error(f'Could not analyze {local_filename}', ffprobe_cmd, ffprobe_result, ffprobe_output)

    probe_data = mmguero.load_str_if_json(' '.join(ffprobe_output))
    if not isinstance(probe_data, dict):
        raise RuntimeError(f'ffprobe returned invalid JSON while analyzing {local_filename}')

    result = {}
    for stream in probe_data.get('streams', []):
        codec_name = stream.get('codec_name')
        codec_type = stream.get('codec_type')
        if codec_name and codec_type:
            result.setdefault(codec_type.lower(), set()).add(codec_name.lower())

    format_names = mmguero.deep_get(probe_data, ['format', 'format_name'])
    if isinstance(format_names, str):
        result['format'] = format_names.split(',')
    elif format_names:
        result['format'] = list(mmguero.get_iterable(format_names))
    else:
        result['format'] = []

    return result


#################################################################################
class Plugger:
    ######## init #################################################################
    def __init__(
        self,
        iFileSpec,
        oFileSpec,
        oAudioFileFormat,
        iSwearsFileSpec,
        outputJson,
        inputTranscript=None,
        saveTranscript=False,
        forceRetranscribe=False,
        aParams=None,
        aChannels=AUDIO_DEFAULT_CHANNELS,
        aSampleRate=AUDIO_DEFAULT_SAMPLE_RATE,
        aBitRate=AUDIO_DEFAULT_BIT_RATE,
        aVorbisQscale=AUDIO_DEFAULT_VORBIS_QSCALE,
        padMsecPre=0,
        padMsecPost=0,
        beep=False,
        beepHertz=BEEP_HERTZ_DEFAULT,
        beepMixNormalize=BEEP_MIX_NORMALIZE_DEFAULT,
        beepAudioWeight=BEEP_AUDIO_WEIGHT_DEFAULT,
        beepSineWeight=BEEP_SINE_WEIGHT_DEFAULT,
        beepDropTransition=BEEP_DROPOUT_TRANSITION_DEFAULT,
        force=False,
        dbug=False,
    ):
        # All runtime state is instance-local. Keeping mutable defaults at class
        # scope can leak transcript/filter data between Plugger instances.
        self.debug = dbug
        self.inputFileSpec = ""
        self.inputCodecs = {}
        self.inputFileParts = None
        self.outputFileSpec = ""
        self.outputAudioFileFormat = ""
        self.outputVideoFileFormat = ""
        self.outputJson = outputJson
        self.tmpDownloadedFileSpec = ""
        self.swearsFileSpec = ""
        self.swearsMap = {}
        self.wordList = []
        self.naughtyWordList = []
        self.muteTimeList = []
        self.sineTimeList = []
        self.beepDelayList = []
        self.aParams = []
        self.inputTranscript = inputTranscript
        self.saveTranscript = saveTranscript
        self.padSecPre = padMsecPre / 1000.0
        self.padSecPost = padMsecPost / 1000.0
        self.beep = beep
        self.beepHertz = beepHertz
        self.beepMixNormalize = beepMixNormalize
        self.beepAudioWeight = beepAudioWeight
        self.beepSineWeight = beepSineWeight
        self.beepDropTransition = beepDropTransition
        self.forceDespiteTag = force

        try:
            if not iFileSpec:
                raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), iFileSpec)

            input_spec = str(iFileSpec)
            input_path = Path(input_spec)
            output_base = None

            # Determine the local input filename, downloading URLs to a unique
            # temporary file so an unrelated file in the working directory can
            # never be overwritten and later removed during cleanup.
            if input_path.is_file():
                self.inputFileSpec = str(input_path)
                output_base = str(input_path.with_suffix(''))
            elif input_spec.lower().startswith(('http://', 'https://')):
                url_name = Path(urlparse(input_spec).path).name
                if not url_name:
                    raise ValueError(f'Unable to determine a filename from URL: {input_spec}')
                self.tmpDownloadedFileSpec = DownloadToFile(input_spec)
                if not self.tmpDownloadedFileSpec or not Path(self.tmpDownloadedFileSpec).is_file():
                    raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), input_spec)
                self.inputFileSpec = self.tmpDownloadedFileSpec
                output_base = str(Path(url_name).with_suffix(''))
            else:
                raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), input_spec)

            self.inputFileParts = os.path.splitext(self.inputFileSpec)
            input_extension = Path(self.inputFileSpec).suffix.lower().lstrip('.')
            self.inputCodecs = GetCodecs(self.inputFileSpec, debug=self.debug)
            input_formats = [str(value).lower() for value in self.inputCodecs.get('format', [])]
            input_format = next(
                (value for value in input_formats if value in AUDIO_DEFAULT_PARAMS_BY_FORMAT),
                None,
            )

            # Determine output filename, either explicitly or from the input.
            self.outputFileSpec = str(oFileSpec) if oFileSpec else output_base + "_clean"
            output_parts = os.path.splitext(self.outputFileSpec)
            if (
                (not oAudioFileFormat or str(oAudioFileFormat).upper() == AUDIO_MATCH_FORMAT)
                and oFileSpec
                and output_parts[1]
            ):
                oAudioFileFormat = output_parts[1].lstrip('.')

            if str(oAudioFileFormat).upper() == AUDIO_MATCH_FORMAT:
                if input_extension in AUDIO_DEFAULT_PARAMS_BY_FORMAT:
                    self.outputFileSpec += '.' + input_extension
                elif input_format:
                    self.outputFileSpec += '.' + input_format
                else:
                    for codec in mmguero.get_iterable(self.inputCodecs.get('audio', [])):
                        output_format = AUDIO_CODEC_TO_FORMAT.get(str(codec).lower())
                        if output_format:
                            self.outputFileSpec += '.' + output_format
                            break
            elif oAudioFileFormat:
                new_suffix = '.' + str(oAudioFileFormat).lower().lstrip('.')
                self.outputFileSpec = mmguero.remove_suffix(self.outputFileSpec, new_suffix) + new_suffix
            else:
                raise ValueError("Output file audio format unspecified")

            output_parts = os.path.splitext(self.outputFileSpec)
            self.outputAudioFileFormat = output_parts[1].lower().lstrip('.')
            if not self.outputAudioFileFormat or (
                not aParams and self.outputAudioFileFormat not in AUDIO_DEFAULT_PARAMS_BY_FORMAT
            ):
                raise ValueError("Output file audio format unspecified or unsupported")

            if aParams:
                audio_params = aParams
                if audio_params.startswith("base64:"):
                    audio_params = base64.b64decode(audio_params[7:]).decode("utf-8")
                self.aParams = shlex.split(audio_params)
            else:
                self.aParams = list(AUDIO_DEFAULT_PARAMS_BY_FORMAT[self.outputAudioFileFormat])

            replacements = {
                CHANNELS_REPLACER: str(aChannels),
                SAMPLE_RATE_REPLACER: str(aSampleRate),
                BIT_RATE_REPLACER: str(aBitRate),
                VORBIS_QSCALE_REPLACER: str(aVorbisQscale),
            }
            self.aParams = [replacements.get(param, param) for param in self.aParams]

            # When MATCH is still in effect for a video input, preserve video
            # streams and replace only the audio stream.
            self.outputVideoFileFormat = (
                self.inputFileParts[1]
                if (
                    mmguero.get_iterable(self.inputCodecs.get('video', []))
                    and str(oAudioFileFormat).upper() == AUDIO_MATCH_FORMAT
                )
                else ''
            )
            if self.outputVideoFileFormat:
                self.outputFileSpec = output_parts[0] + self.outputVideoFileFormat

            self._ensure_directory_exists(self.outputFileSpec, "output directory")

            # If save-transcript is enabled and no explicit JSON output path,
            # place the transcript alongside the requested output file.
            if self.saveTranscript and not self.outputJson:
                self.outputJson = os.path.splitext(self.outputFileSpec)[0] + '_transcript.json'
                if self.debug:
                    mmguero.eprint(f'Auto-generated transcript output: {self.outputJson}')

            if self.saveTranscript and not self.inputTranscript and self.outputJson and not forceRetranscribe:
                if Path(self.outputJson).exists():
                    self.inputTranscript = self.outputJson
                    if self.debug:
                        mmguero.eprint(f'Found existing transcript, reusing: {self.inputTranscript}')

            if self.outputJson:
                self._ensure_directory_exists(self.outputJson, "JSON output directory")

            if iSwearsFileSpec and Path(iSwearsFileSpec).is_file():
                self.swearsFileSpec = str(iSwearsFileSpec)
            else:
                raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), iSwearsFileSpec)

            self._load_swears_file()
        except Exception:
            self.cleanup()
            raise

        if self.debug:
            mmguero.eprint(f'Input: {self.inputFileSpec}')
            mmguero.eprint(f'Input codec: {self.inputCodecs}')
            mmguero.eprint(f'Output: {self.outputFileSpec}')
            mmguero.eprint(f'Output audio format: {self.outputAudioFileFormat}')
            mmguero.eprint(f'Encode parameters: {self.aParams}')
            mmguero.eprint(f'Profanity file: {self.swearsFileSpec}')
            mmguero.eprint(f'Intermediate downloaded file: {self.tmpDownloadedFileSpec}')
            if self.outputJson:
                mmguero.eprint(f'Transcript output: {self.outputJson}')
            if self.inputTranscript:
                mmguero.eprint(f'Input transcript: {self.inputTranscript}')
            mmguero.eprint(f'Beep instead of mute: {self.beep}')
            if self.beep:
                mmguero.eprint(f'Beep hertz: {self.beepHertz}')
                mmguero.eprint(f'Beep mix normalization: {self.beepMixNormalize}')
                mmguero.eprint(f'Beep audio weight: {self.beepAudioWeight}')
                mmguero.eprint(f'Beep sine weight: {self.beepSineWeight}')
                mmguero.eprint(f'Beep dropout transition: {self.beepDropTransition}')
            mmguero.eprint(f'Force despite tags: {self.forceDespiteTag}')

    ######## cleanup ##############################################################
    def cleanup(self):
        """Remove temporary files owned by this instance."""
        _safe_unlink(self.tmpDownloadedFileSpec)
        self.tmpDownloadedFileSpec = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.cleanup()
        return False

    ######## _ensure_directory_exists #############################################
    def _ensure_directory_exists(self, filepath, description="directory"):
        """Ensure the parent directory for filepath exists."""
        directory = Path(filepath).expanduser().parent
        if directory != Path('.') and not directory.exists():
            if self.debug:
                mmguero.eprint(f'Creating {description}: {directory}')
            directory.mkdir(parents=True, exist_ok=True)
        return str(directory)

    ######## LoadTranscriptFromFile ###############################################
    def LoadTranscriptFromFile(self):
        """Load a pre-generated transcript from a JSON file."""
        if not self.inputTranscript:
            return False

        transcript_path = Path(self.inputTranscript)
        if not transcript_path.is_file():
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), self.inputTranscript)

        if self.debug:
            mmguero.eprint(f'Loading transcript from: {self.inputTranscript}')

        with transcript_path.open('r', encoding='utf-8') as file_handle:
            word_list = json.load(file_handle)
        if not isinstance(word_list, list):
            raise ValueError(
                f'Transcript JSON must contain an array of words, got {type(word_list).__name__}'
            )
        self.wordList = word_list

        for word in self.wordList:
            word['scrub'] = scrubword(word.get('word', '')) in self.swearsMap

        if self.debug:
            mmguero.eprint(f'Loaded {len(self.wordList)} words from transcript')
            scrubbed_count = sum(1 for word in self.wordList if word.get('scrub'))
            mmguero.eprint(f'Words to censor with current swear list: {scrubbed_count}')

        return True

    ######## _load_swears_file ####################################################
    def _load_swears_file(self):
        """Load profanity entries from JSON or legacy pipe-delimited text."""
        swear_path = Path(self.swearsFileSpec)
        content = swear_path.read_text(encoding='utf-8')
        self.swearsMap = {}

        if swear_path.suffix.lower() == '.json':
            self._load_swears_from_json_data(json.loads(content))
        else:
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                self._load_swears_from_text_content(content)
            else:
                self._load_swears_from_json_data(data)

        if self.debug:
            mmguero.eprint(f'Loaded {len(self.swearsMap)} profanity entries from {self.swearsFileSpec}')

    def _load_swears_from_json_data(self, data):
        if not isinstance(data, list):
            raise ValueError(f"JSON swears file must contain an array of strings, got {type(data).__name__}")

        for item in data:
            if isinstance(item, str):
                normalized = scrubword(item)
                if normalized:
                    self.swearsMap[normalized] = "*****"

    def _load_swears_from_text_content(self, content):
        for raw_line in content.splitlines():
            if not raw_line.strip():
                continue
            word, separator, replacement = raw_line.partition('|')
            normalized = scrubword(word)
            if not normalized:
                continue
            self.swearsMap[normalized] = replacement if separator else "*****"

    ######## CreateCleanMuteList ##################################################
    def CreateCleanMuteList(self):
        if not self.LoadTranscriptFromFile():
            self.RecognizeSpeech()

        self.naughtyWordList = [word for word in self.wordList if word.get("scrub")]
        if self.debug:
            mmguero.eprint(self.naughtyWordList)

        intervals = []
        for word in self.naughtyWordList:
            try:
                start = round(max(0.0, float(word['start']) - self.padSecPre), 3)
                end = round(max(0.0, float(word['end']) + self.padSecPost), 3)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f'Invalid transcript word timing: {word!r}') from exc

            if end <= start:
                if self.debug:
                    mmguero.eprint(f'Skipping non-positive mute interval: {start:.3f}-{end:.3f}')
                continue
            intervals.append((start, end))

        intervals.sort()
        merged_intervals = []
        for start, end in intervals:
            if merged_intervals and start <= merged_intervals[-1][1]:
                previous_start, previous_end = merged_intervals[-1]
                merged_intervals[-1] = (previous_start, max(previous_end, end))
            else:
                merged_intervals.append((start, end))

        self.muteTimeList = []
        self.sineTimeList = []
        self.beepDelayList = []
        fade_duration = 0.005

        for index, (start, end) in enumerate(merged_intervals):
            word_start = f'{start:.3f}'
            word_end = f'{end:.3f}'
            duration = f'{end - start:.3f}'

            if self.beep:
                self.muteTimeList.append(
                    f"volume=enable='between(t,{word_start},{word_end})':volume=0"
                )
                self.sineTimeList.append(f"sine=f={self.beepHertz}:duration={duration}")
                delay_ms = str(int(round(start * 1000)))
                self.beepDelayList.append(f"atrim=0:{duration},adelay={delay_ms}|{delay_ms}")
                continue

            self.muteTimeList.append(
                f"afade=enable='between(t,{word_start},{word_end})':"
                f"t=out:st={word_start}:d=5ms"
            )

            next_start = merged_intervals[index + 1][0] if index + 1 < len(merged_intervals) else None
            fade_in_end = end + fade_duration
            if next_start is not None:
                fade_in_end = min(fade_in_end, next_start)
            fade_in_end = round(fade_in_end, 3)
            if fade_in_end > end:
                self.muteTimeList.append(
                    f"afade=enable='between(t,{word_end},{fade_in_end:.3f})':"
                    f"t=in:st={word_end}:d=5ms"
                )

        if self.debug:
            mmguero.eprint(self.muteTimeList)
            if self.beep:
                mmguero.eprint(self.sineTimeList)
                mmguero.eprint(self.beepDelayList)

        return self.muteTimeList

    def _build_filter_graph(self):
        if not self.muteTimeList:
            return None, None

        if not self.beep:
            return '-/filter:a', ','.join(self.muteTimeList)

        mute_filters = ','.join(self.muteTimeList)
        sine_filters = ';'.join(
            f'{value}[beep{index + 1}]' for index, value in enumerate(self.sineTimeList)
        )
        delay_filters = ';'.join(
            f'[beep{index + 1}]{value}[beep{index + 1}_delayed]'
            for index, value in enumerate(self.beepDelayList)
        )
        mix_inputs = ''.join(
            f'[beep{index + 1}_delayed]' for index in range(len(self.beepDelayList))
        )
        sine_weights = ' '.join(str(self.beepSineWeight) for _ in self.beepDelayList)
        filter_graph = (
            f"[0:a]{mute_filters}[mute];{sine_filters};{delay_filters};"
            f"[mute]{mix_inputs}amix=inputs={len(self.beepDelayList) + 1}:"
            f"normalize={str(self.beepMixNormalize).lower()}:"
            f"dropout_transition={self.beepDropTransition}:"
            f"weights={self.beepAudioWeight} {sine_weights}"
        )
        return '-/filter_complex', filter_graph

    def _build_ffmpeg_command(self, output_file, audio_args):
        command = [
            'ffmpeg',
            '-nostdin',
            '-hide_banner',
            '-nostats',
            '-loglevel',
            'error',
            '-y',
            '-i',
            self.inputFileSpec,
        ]
        if self.outputVideoFileFormat:
            command.extend(['-c:v', 'copy', '-sn', '-dn'])
        else:
            command.extend(['-vn', '-sn', '-dn'])
        command.extend(audio_args)
        command.extend(self.aParams)
        command.append(output_file)
        return command

    ######## EncodeCleanAudio #####################################################
    def EncodeCleanAudio(self):
        should_process = self.forceDespiteTag or not GetMonkeyplugTagged(
            self.inputFileSpec, debug=self.debug
        )

        with _temporary_output_path(self.outputFileSpec) as temporary_output:
            if should_process:
                self.CreateCleanMuteList()
                filter_arg, filter_graph = self._build_filter_graph()

                if filter_graph is not None:
                    with tempfile.TemporaryDirectory(prefix='monkeyplug_filter_') as filter_tmp_dir:
                        filter_file_spec = str(Path(filter_tmp_dir) / 'filters.txt')
                        Path(filter_file_spec).write_text(filter_graph, encoding='utf-8')
                        if self.debug:
                            mmguero.eprint(f'FFmpeg filter file: {filter_file_spec}')
                        ffmpeg_cmd = self._build_ffmpeg_command(
                            temporary_output, [filter_arg, filter_file_spec]
                        )
                        ffmpeg_result, ffmpeg_output = mmguero.run_process(
                            ffmpeg_cmd, stdout=True, stderr=True, debug=self.debug
                        )
                else:
                    ffmpeg_cmd = self._build_ffmpeg_command(temporary_output, [])
                    ffmpeg_result, ffmpeg_output = mmguero.run_process(
                        ffmpeg_cmd, stdout=True, stderr=True, debug=self.debug
                    )

                if ffmpeg_result != 0 or not Path(temporary_output).is_file():
                    _raise_process_error(
                        f'Could not process {self.inputFileSpec}',
                        ffmpeg_cmd,
                        ffmpeg_result,
                        ffmpeg_output,
                    )

                SetMonkeyplugTag(temporary_output, debug=self.debug)
            else:
                shutil.copyfile(self.inputFileSpec, temporary_output)

            os.replace(temporary_output, self.outputFileSpec)

        return self.outputFileSpec


#################################################################################


#################################################################################
class VoskPlugger(Plugger):
    def __init__(
        self,
        iFileSpec,
        oFileSpec,
        oAudioFileFormat,
        iSwearsFileSpec,
        mDir,
        outputJson,
        inputTranscript=None,
        saveTranscript=False,
        forceRetranscribe=False,
        aParams=None,
        aChannels=AUDIO_DEFAULT_CHANNELS,
        aSampleRate=AUDIO_DEFAULT_SAMPLE_RATE,
        aBitRate=AUDIO_DEFAULT_BIT_RATE,
        aVorbisQscale=AUDIO_DEFAULT_VORBIS_QSCALE,
        wChunk=AUDIO_DEFAULT_WAV_FRAMES_CHUNK,
        padMsecPre=0,
        padMsecPost=0,
        beep=False,
        beepHertz=BEEP_HERTZ_DEFAULT,
        beepMixNormalize=BEEP_MIX_NORMALIZE_DEFAULT,
        beepAudioWeight=BEEP_AUDIO_WEIGHT_DEFAULT,
        beepSineWeight=BEEP_SINE_WEIGHT_DEFAULT,
        beepDropTransition=BEEP_DROPOUT_TRANSITION_DEFAULT,
        force=False,
        dbug=False,
    ):
        self.tmpWavFileSpec = ""
        self.wavReadFramesChunk = wChunk
        self.modelPath = None
        self.vosk = None

        if not inputTranscript:
            if mDir and Path(mDir).is_dir():
                self.modelPath = str(mDir)
            else:
                raise FileNotFoundError(
                    errno.ENOENT,
                    os.strerror(errno.ENOENT) + " (see https://alphacephei.com/vosk/models)",
                    mDir,
                )

            self.vosk = mmguero.dynamic_import("vosk", "vosk", debug=dbug)
            if not self.vosk:
                raise RuntimeError("Unable to initialize VOSK API")
            if not dbug:
                self.vosk.SetLogLevel(-1)

        super().__init__(
            iFileSpec=iFileSpec,
            oFileSpec=oFileSpec,
            oAudioFileFormat=oAudioFileFormat,
            iSwearsFileSpec=iSwearsFileSpec,
            outputJson=outputJson,
            inputTranscript=inputTranscript,
            saveTranscript=saveTranscript,
            forceRetranscribe=forceRetranscribe,
            aParams=aParams,
            aChannels=aChannels,
            aSampleRate=aSampleRate,
            aBitRate=aBitRate,
            aVorbisQscale=aVorbisQscale,
            padMsecPre=padMsecPre,
            padMsecPost=padMsecPost,
            beep=beep,
            beepHertz=beepHertz,
            beepMixNormalize=beepMixNormalize,
            beepAudioWeight=beepAudioWeight,
            beepSineWeight=beepSineWeight,
            beepDropTransition=beepDropTransition,
            force=force,
            dbug=dbug,
        )

        if self.debug:
            if inputTranscript:
                mmguero.eprint('Using input transcript (skipping speech recognition)')
            else:
                mmguero.eprint(f'Model directory: {self.modelPath}')
                mmguero.eprint(f'Read frames: {self.wavReadFramesChunk}')

    def cleanup(self):
        _safe_unlink(self.tmpWavFileSpec)
        self.tmpWavFileSpec = ""
        super().cleanup()

    def CreateIntermediateWAV(self):
        _safe_unlink(self.tmpWavFileSpec)
        with tempfile.NamedTemporaryFile(prefix='monkeyplug_', suffix='.wav', delete=False) as tmp_file:
            self.tmpWavFileSpec = tmp_file.name

        if self.debug:
            mmguero.eprint(f'Intermediate audio file: {self.tmpWavFileSpec}')

        ffmpeg_cmd = [
            'ffmpeg',
            '-nostdin',
            '-hide_banner',
            '-nostats',
            '-loglevel',
            'error',
            '-y',
            '-i',
            self.inputFileSpec,
            '-vn',
            '-sn',
            '-dn',
            *AUDIO_INTERMEDIATE_PARAMS,
            self.tmpWavFileSpec,
        ]
        ffmpeg_result, ffmpeg_output = mmguero.run_process(
            ffmpeg_cmd, stdout=True, stderr=True, debug=self.debug
        )
        if ffmpeg_result != 0 or not Path(self.tmpWavFileSpec).is_file():
            _raise_process_error(
                f'Could not convert {self.inputFileSpec} to 16 kHz mono PCM WAV',
                ffmpeg_cmd,
                ffmpeg_result,
                ffmpeg_output,
            )

        return self.inputFileSpec

    def RecognizeSpeech(self):
        self.CreateIntermediateWAV()
        self.wordList = []
        with wave.open(self.tmpWavFileSpec, "rb") as wav_file:
            if (
                wav_file.getnchannels() != 1
                or wav_file.getframerate() != 16000
                or wav_file.getsampwidth() != 2
                or wav_file.getcomptype() != "NONE"
            ):
                raise RuntimeError(
                    f"Audio file ({self.tmpWavFileSpec}) must be 16 kHz, mono, s16 PCM WAV"
                )

            recognizer = self.vosk.KaldiRecognizer(self.vosk.Model(self.modelPath), wav_file.getframerate())
            recognizer.SetWords(True)
            while True:
                data = wav_file.readframes(self.wavReadFramesChunk)
                if not data:
                    break
                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    for word in result.get("result", []):
                        word['scrub'] = scrubword(mmguero.deep_get(word, ["word"])) in self.swearsMap
                        self.wordList.append(word)

            result = json.loads(recognizer.FinalResult())
            for word in result.get("result", []):
                word['scrub'] = scrubword(mmguero.deep_get(word, ["word"])) in self.swearsMap
                self.wordList.append(word)

        if self.debug:
            mmguero.eprint(json.dumps(self.wordList))

        if self.outputJson:
            _write_json_atomic(self.outputJson, self.wordList)

        return self.wordList


#################################################################################


#################################################################################
class WhisperPlugger(Plugger):
    def __init__(
        self,
        iFileSpec,
        oFileSpec,
        oAudioFileFormat,
        iSwearsFileSpec,
        mDir,
        mName,
        torchThreads,
        outputJson,
        inputTranscript=None,
        saveTranscript=False,
        forceRetranscribe=False,
        aParams=None,
        aChannels=AUDIO_DEFAULT_CHANNELS,
        aSampleRate=AUDIO_DEFAULT_SAMPLE_RATE,
        aBitRate=AUDIO_DEFAULT_BIT_RATE,
        aVorbisQscale=AUDIO_DEFAULT_VORBIS_QSCALE,
        padMsecPre=0,
        padMsecPost=0,
        beep=False,
        beepHertz=BEEP_HERTZ_DEFAULT,
        beepMixNormalize=BEEP_MIX_NORMALIZE_DEFAULT,
        beepAudioWeight=BEEP_AUDIO_WEIGHT_DEFAULT,
        beepSineWeight=BEEP_SINE_WEIGHT_DEFAULT,
        beepDropTransition=BEEP_DROPOUT_TRANSITION_DEFAULT,
        force=False,
        dbug=False,
    ):
        self.whisper = None
        self.model = None
        self.torch = None
        self.transcript = None

        if not inputTranscript:
            if torchThreads > 0:
                self.torch = mmguero.dynamic_import("torch", "torch", debug=dbug)
                if self.torch:
                    self.torch.set_num_threads(torchThreads)

            self.whisper = mmguero.dynamic_import("whisper", "openai-whisper", debug=dbug)
            if not self.whisper:
                raise RuntimeError("Unable to initialize Whisper API")

            self.model = self.whisper.load_model(mName, download_root=mDir)
            if not self.model:
                raise RuntimeError(f"Unable to load Whisper model {mName} in {mDir}")

        super().__init__(
            iFileSpec=iFileSpec,
            oFileSpec=oFileSpec,
            oAudioFileFormat=oAudioFileFormat,
            iSwearsFileSpec=iSwearsFileSpec,
            outputJson=outputJson,
            inputTranscript=inputTranscript,
            saveTranscript=saveTranscript,
            forceRetranscribe=forceRetranscribe,
            aParams=aParams,
            aChannels=aChannels,
            aSampleRate=aSampleRate,
            aBitRate=aBitRate,
            aVorbisQscale=aVorbisQscale,
            padMsecPre=padMsecPre,
            padMsecPost=padMsecPost,
            beep=beep,
            beepHertz=beepHertz,
            beepMixNormalize=beepMixNormalize,
            beepAudioWeight=beepAudioWeight,
            beepSineWeight=beepSineWeight,
            beepDropTransition=beepDropTransition,
            force=force,
            dbug=dbug,
        )

        if self.debug:
            if inputTranscript:
                mmguero.eprint('Using input transcript (skipping speech recognition)')
            else:
                mmguero.eprint(f'Model directory: {mDir}')
                mmguero.eprint(f'Model name: {mName}')

    def RecognizeSpeech(self):
        self.wordList = []
        self.transcript = self.model.transcribe(word_timestamps=True, audio=self.inputFileSpec)
        if self.transcript and 'segments' in self.transcript:
            for segment in self.transcript['segments']:
                for word in segment.get('words', []):
                    word['word'] = word['word'].strip()
                    word['scrub'] = scrubword(word['word']) in self.swearsMap
                    self.wordList.append(word)

        if self.debug:
            mmguero.eprint(json.dumps(self.wordList))

        if self.outputJson:
            _write_json_atomic(self.outputJson, self.wordList)

        return self.wordList


#################################################################################


###################################################################################################
# RunMonkeyPlug
def RunMonkeyPlug():

    package_name = __package__ or "monkeyplug"
    try:
        metadata = importlib.metadata.metadata(package_name)
        version = metadata.get("Version", "unknown")
    except importlib.metadata.PackageNotFoundError:
        version = "source"

    parser = argparse.ArgumentParser(
        description=f"{package_name} (v{version})",
        add_help=True,
        usage=f"{package_name} <arguments>",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        dest="debug",
        type=mmguero.str2bool,
        nargs="?",
        const=True,
        default=False,
        metavar="true|false",
        help="Verbose/debug output",
    )
    parser.add_argument(
        "-m",
        "--mode",
        dest="speechRecMode",
        metavar="<string>",
        type=str,
        default=DEFAULT_SPEECH_REC_MODE,
        help=f"Speech recognition engine ({SPEECH_REC_MODE_WHISPER}|{SPEECH_REC_MODE_VOSK}) (default: {DEFAULT_SPEECH_REC_MODE})",
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input",
        type=str,
        default=None,
        required=True,
        metavar="<string>",
        help="Input file (or URL)",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        type=str,
        default=None,
        required=False,
        metavar="<string>",
        help="Output file",
    )
    parser.add_argument(
        "--output-json",
        dest="outputJson",
        type=str,
        default=None,
        required=False,
        metavar="<string>",
        help="Output file to store transcript JSON",
    )
    parser.add_argument(
        "-w",
        "--swears",
        help=f"text file containing profanity (default: \"{SWEARS_FILENAME_DEFAULT}\")",
        default=os.path.join(script_path, SWEARS_FILENAME_DEFAULT),
        metavar="<profanity file>",
    )
    parser.add_argument(
        "--input-transcript",
        dest="inputTranscript",
        type=str,
        default=None,
        required=False,
        metavar="<string>",
        help="Load existing transcript JSON instead of performing speech recognition",
    )
    parser.add_argument(
        "--save-transcript",
        dest="saveTranscript",
        action="store_true",
        default=False,
        help="Automatically save transcript JSON alongside output audio file",
    )
    parser.add_argument(
        "--force-retranscribe",
        dest="forceRetranscribe",
        action="store_true",
        default=False,
        help="Force new transcription even if transcript file exists (overrides automatic reuse)",
    )
    parser.add_argument(
        "-a",
        "--audio-params",
        help="Audio parameters for ffmpeg (default depends on output audio codec)",
        dest="aParams",
        metavar="<str>",
        default=None,
    )
    parser.add_argument(
        "-c",
        "--channels",
        dest="aChannels",
        metavar="<int>",
        type=int,
        default=AUDIO_DEFAULT_CHANNELS,
        help=f"Audio output channels (default: {AUDIO_DEFAULT_CHANNELS})",
    )
    parser.add_argument(
        "-s",
        "--sample-rate",
        dest="aSampleRate",
        metavar="<int>",
        type=int,
        default=AUDIO_DEFAULT_SAMPLE_RATE,
        help=f"Audio output sample rate (default: {AUDIO_DEFAULT_SAMPLE_RATE})",
    )
    parser.add_argument(
        "-r",
        "--bitrate",
        dest="aBitRate",
        metavar="<str>",
        default=AUDIO_DEFAULT_BIT_RATE,
        help=f"Audio output bitrate (default: {AUDIO_DEFAULT_BIT_RATE})",
    )
    parser.add_argument(
        "-q",
        "--vorbis-qscale",
        dest="aVorbisQscale",
        metavar="<int>",
        type=int,
        default=AUDIO_DEFAULT_VORBIS_QSCALE,
        help=f"qscale for libvorbis output (default: {AUDIO_DEFAULT_VORBIS_QSCALE})",
    )
    parser.add_argument(
        "-f",
        "--format",
        dest="outputFormat",
        type=str,
        default=AUDIO_MATCH_FORMAT,
        required=False,
        metavar="<string>",
        help=f"Output file format (default: inferred from extension of --output, or \"{AUDIO_MATCH_FORMAT}\")",
    )
    parser.add_argument(
        "--pad-milliseconds",
        dest="padMsec",
        metavar="<int>",
        type=int,
        default=0,
        help="Milliseconds to pad on either side of muted segments (default: 0)",
    )
    parser.add_argument(
        "--pad-milliseconds-pre",
        dest="padMsecPre",
        metavar="<int>",
        type=int,
        default=0,
        help="Milliseconds to pad before muted segments (default: 0)",
    )
    parser.add_argument(
        "--pad-milliseconds-post",
        dest="padMsecPost",
        metavar="<int>",
        type=int,
        default=0,
        help="Milliseconds to pad after muted segments (default: 0)",
    )
    parser.add_argument(
        "-b",
        "--beep",
        dest="beep",
        type=mmguero.str2bool,
        nargs="?",
        const=True,
        default=False,
        metavar="true|false",
        help="Beep instead of silence",
    )
    parser.add_argument(
        "-z",
        "--beep-hertz",
        dest="beepHertz",
        metavar="<int>",
        type=int,
        default=BEEP_HERTZ_DEFAULT,
        help=f"Beep frequency hertz (default: {BEEP_HERTZ_DEFAULT})",
    )
    parser.add_argument(
        "--beep-mix-normalize",
        dest="beepMixNormalize",
        type=mmguero.str2bool,
        nargs="?",
        const=True,
        default=BEEP_MIX_NORMALIZE_DEFAULT,
        metavar="true|false",
        help=f"Normalize mix of audio and beeps (default: {BEEP_MIX_NORMALIZE_DEFAULT})",
    )
    parser.add_argument(
        "--beep-audio-weight",
        dest="beepAudioWeight",
        metavar="<int>",
        type=int,
        default=BEEP_AUDIO_WEIGHT_DEFAULT,
        help=f"Mix weight for non-beeped audio (default: {BEEP_AUDIO_WEIGHT_DEFAULT})",
    )
    parser.add_argument(
        "--beep-sine-weight",
        dest="beepSineWeight",
        metavar="<int>",
        type=int,
        default=BEEP_SINE_WEIGHT_DEFAULT,
        help=f"Mix weight for beep (default: {BEEP_SINE_WEIGHT_DEFAULT})",
    )
    parser.add_argument(
        "--beep-dropout-transition",
        dest="beepDropTransition",
        metavar="<int>",
        type=int,
        default=BEEP_DROPOUT_TRANSITION_DEFAULT,
        help=f"Dropout transition for beep (default: {BEEP_DROPOUT_TRANSITION_DEFAULT})",
    )

    parser.add_argument(
        "--force",
        dest="forceDespiteTag",
        type=mmguero.str2bool,
        nargs="?",
        const=True,
        default=False,
        metavar="true|false",
        help="Process file despite existence of embedded tag",
    )

    voskArgGroup = parser.add_argument_group('VOSK Options')
    voskArgGroup.add_argument(
        "--vosk-model-dir",
        dest="voskModelDir",
        metavar="<string>",
        type=str,
        default=DEFAULT_VOSK_MODEL_DIR,
        help=f"VOSK model directory (default: {DEFAULT_VOSK_MODEL_DIR})",
    )
    voskArgGroup.add_argument(
        "--vosk-read-frames-chunk",
        dest="voskReadFramesChunk",
        metavar="<int>",
        type=int,
        default=int(os.getenv("VOSK_READ_FRAMES", AUDIO_DEFAULT_WAV_FRAMES_CHUNK)),
        help=f"WAV frame chunk (default: {AUDIO_DEFAULT_WAV_FRAMES_CHUNK})",
    )

    whisperArgGroup = parser.add_argument_group('Whisper Options')
    whisperArgGroup.add_argument(
        "--whisper-model-dir",
        dest="whisperModelDir",
        metavar="<string>",
        type=str,
        default=DEFAULT_WHISPER_MODEL_DIR,
        help=f"Whisper model directory ({DEFAULT_WHISPER_MODEL_DIR})",
    )
    whisperArgGroup.add_argument(
        "--whisper-model-name",
        dest="whisperModelName",
        metavar="<string>",
        type=str,
        default=DEFAULT_WHISPER_MODEL_NAME,
        help=f"Whisper model name ({DEFAULT_WHISPER_MODEL_NAME})",
    )
    whisperArgGroup.add_argument(
        "--torch-threads",
        dest="torchThreads",
        metavar="<int>",
        type=int,
        default=DEFAULT_TORCH_THREADS,
        help=f"Number of threads used by torch for CPU inference ({DEFAULT_TORCH_THREADS})",
    )

    args = parser.parse_args()

    if args.debug:
        mmguero.eprint(str(script_file))
        mmguero.eprint(f"Arguments: {sys.argv[1:]}")
        mmguero.eprint(f"Arguments: {args}")
    else:
        sys.tracebacklimit = 0

    if args.speechRecMode == SPEECH_REC_MODE_VOSK:
        Path(args.voskModelDir).mkdir(parents=True, exist_ok=True)
        plug = VoskPlugger(
            args.input,
            args.output,
            args.outputFormat,
            args.swears,
            args.voskModelDir,
            args.outputJson,
            inputTranscript=args.inputTranscript,
            saveTranscript=args.saveTranscript,
            forceRetranscribe=args.forceRetranscribe,
            aParams=args.aParams,
            aChannels=args.aChannels,
            aSampleRate=args.aSampleRate,
            aBitRate=args.aBitRate,
            aVorbisQscale=args.aVorbisQscale,
            wChunk=args.voskReadFramesChunk,
            padMsecPre=args.padMsecPre if args.padMsecPre > 0 else args.padMsec,
            padMsecPost=args.padMsecPost if args.padMsecPost > 0 else args.padMsec,
            beep=args.beep,
            beepHertz=args.beepHertz,
            beepMixNormalize=args.beepMixNormalize,
            beepAudioWeight=args.beepAudioWeight,
            beepSineWeight=args.beepSineWeight,
            beepDropTransition=args.beepDropTransition,
            force=args.forceDespiteTag,
            dbug=args.debug,
        )
    elif args.speechRecMode == SPEECH_REC_MODE_WHISPER:
        Path(args.whisperModelDir).mkdir(parents=True, exist_ok=True)
        plug = WhisperPlugger(
            args.input,
            args.output,
            args.outputFormat,
            args.swears,
            args.whisperModelDir,
            args.whisperModelName,
            args.torchThreads,
            args.outputJson,
            inputTranscript=args.inputTranscript,
            saveTranscript=args.saveTranscript,
            forceRetranscribe=args.forceRetranscribe,
            aParams=args.aParams,
            aChannels=args.aChannels,
            aSampleRate=args.aSampleRate,
            aBitRate=args.aBitRate,
            aVorbisQscale=args.aVorbisQscale,
            padMsecPre=args.padMsecPre if args.padMsecPre > 0 else args.padMsec,
            padMsecPost=args.padMsecPost if args.padMsecPost > 0 else args.padMsec,
            beep=args.beep,
            beepHertz=args.beepHertz,
            beepMixNormalize=args.beepMixNormalize,
            beepAudioWeight=args.beepAudioWeight,
            beepSineWeight=args.beepSineWeight,
            beepDropTransition=args.beepDropTransition,
            force=args.forceDespiteTag,
            dbug=args.debug,
        )
    else:
        raise ValueError(f"Unsupported speech recognition engine {args.speechRecMode}")

    with plug:
        print(plug.EncodeCleanAudio())

    sys.exit(0)


###################################################################################################
if __name__ == "__main__":
    RunMonkeyPlug()
