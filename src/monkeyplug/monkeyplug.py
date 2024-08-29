#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import base64
import errno
import json
import mmguero
import mutagen
import os
import pathlib
import requests
import shutil
import string
import sys
import wave

from urllib.parse import urlparse
from itertools import tee

###################################################################################################
CHANNELS_REPLACER = 'CHANNELS'
AUDIO_DEFAULT_PARAMS_BY_FORMAT = {
    "flac": ["-c:a", "flac", "-ar", "44100", "-ac", CHANNELS_REPLACER],
    "m4a": ["-c:a", "aac", "-b:a", "128K", "-ar", "44100", "-ac", CHANNELS_REPLACER],
    "aac": ["-c:a", "aac", "-b:a", "128K", "-ar", "44100", "-ac", CHANNELS_REPLACER],
    "mp3": ["-c:a", "libmp3lame", "-b:a", "128K", "-ar", "44100", "-ac", CHANNELS_REPLACER],
    "ogg": ["-c:a", "libvorbis", "-qscale:a", "5", "-ar", "44100", "-ac", CHANNELS_REPLACER],
    "opus": ["-c:a", "libopus", "-b:a", "128K", "-ar", "48000", "-ac", CHANNELS_REPLACER],
    "ac3": ["-c:a", "ac3", "-b:a", "128K", "-ar", "44100", "-ac", CHANNELS_REPLACER],
}
AUDIO_CODEC_TO_FORMAT = {
    "aac": "m4a",
    "ac3": "ac3",
    "flac": "flac",
    "mp3": "mp3",
    "opus": "opus",
    "vorbis": "ogg",
}

AUDIO_DEFAULT_FORMAT = "mp3"
AUDIO_DEFAULT_CHANNELS = 2
AUDIO_MATCH_FORMAT = "MATCH"
AUDIO_INTERMEDIATE_PARAMS = ["-c:a", "pcm_s16le", "-ac", "1", "-ar", "16000"]
AUDIO_DEFAULT_WAV_FRAMES_CHUNK = 8000
BEEP_HERTZ_DEFAULT = 1000
SWEARS_FILENAME_DEFAULT = 'swears.txt'
MUTAGEN_METADATA_TAGS = ['encodedby', 'comment']
MUTAGEN_METADATA_TAG_VALUE = u'monkeyplug'
SPEECH_REC_MODE_VOSK = "vosk"
SPEECH_REC_MODE_WHISPER = "whisper"
DEFAULT_SPEECH_REC_MODE = os.getenv("MONKEYPLUG_MODE", SPEECH_REC_MODE_WHISPER)
DEFAULT_VOSK_MODEL_DIR = os.getenv(
    "VOSK_MODEL_DIR", os.path.join(os.path.join(os.path.join(os.path.expanduser("~"), '.cache'), 'vosk'))
)
DEFAULT_WHISPER_MODEL_DIR = os.getenv(
    "WHISPER_MODEL_DIR", os.path.join(os.path.join(os.path.join(os.path.expanduser("~"), '.cache'), 'whisper'))
)
DEFAULT_WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL_NAME", "small.en")

###################################################################################################
script_name = os.path.basename(__file__)
script_path = os.path.dirname(os.path.realpath(__file__))


# thanks https://docs.python.org/3/library/itertools.html#recipes
def pairwise(iterable):
    a, b = tee(iterable)
    next(b, None)
    return zip(a, b)


def scrubword(value):
    return str(value).lower().strip().translate(str.maketrans('', '', string.punctuation))


###################################################################################################
# download to file
def DownloadToFile(url, local_filename=None, chunk_bytes=4096, debug=False):
    tmpDownloadedFileSpec = local_filename if local_filename else os.path.basename(urlparse(url).path)
    r = requests.get(url, stream=True, allow_redirects=True)
    with open(tmpDownloadedFileSpec, "wb") as f:
        for chunk in r.iter_content(chunk_size=chunk_bytes):
            if chunk:
                f.write(chunk)
    fExists = os.path.isfile(tmpDownloadedFileSpec)
    fSize = os.path.getsize(tmpDownloadedFileSpec)
    if debug:
        mmguero.eprint(
            f"Download of {url} to {tmpDownloadedFileSpec} {'succeeded' if fExists else 'failed'} ({mmguero.SizeHumanFormat(fSize)})"
        )

    if fExists and (fSize > 0):
        return tmpDownloadedFileSpec
    else:
        if fExists:
            os.remove(tmpDownloadedFileSpec)
        return None


###################################################################################################
# Get tag from file to indicate monkeyplug has already been set
def GetMonkeyplugTagged(local_filename, debug=False):
    result = False
    if os.path.isfile(local_filename):
        mut = mutagen.File(local_filename, easy=True)
        if debug:
            mmguero.eprint(f'Tags of {local_filename}: {mut}')
        if hasattr(mut, 'get'):
            for tag in MUTAGEN_METADATA_TAGS:
                try:
                    if MUTAGEN_METADATA_TAG_VALUE in mmguero.GetIterable(mut.get(tag, default=())):
                        result = True
                        break
                except Exception as e:
                    if debug:
                        mmguero.eprint(e)
    return result


###################################################################################################
# Set tag to file to indicate monkeyplug has worked its magic
def SetMonkeyplugTag(local_filename, debug=False):
    result = False
    if os.path.isfile(local_filename):
        mut = mutagen.File(local_filename, easy=True)
        if debug:
            mmguero.eprint(f'Tags of {local_filename} before: {mut}')
        if hasattr(mut, '__setitem__'):
            for tag in MUTAGEN_METADATA_TAGS:
                try:
                    mut[tag] = MUTAGEN_METADATA_TAG_VALUE
                    result = True
                    break
                except mutagen.MutagenError as me:
                    if debug:
                        mmguero.eprint(me)
            if result:
                try:
                    mut.save(local_filename)
                except Exception as e:
                    result = False
                    mmguero.eprint(e)
            if debug:
                mmguero.eprint(f'Tags of {local_filename} after: {mut}')

    return result


###################################################################################################
# get stream codecs from an input filename
# e.g. result: {'video': {'h264'}, 'audio': {'eac3'}, 'subtitle': {'subrip'}}
def GetCodecs(local_filename, debug=False):
    result = {}
    if os.path.isfile(local_filename):
        ffprobeCmd = [
            'ffprobe',
            '-v',
            'quiet',
            '-print_format',
            'json',
            '-show_format',
            '-show_streams',
            local_filename,
        ]
        ffprobeResult, ffprobeOutput = mmguero.RunProcess(ffprobeCmd, stdout=True, stderr=False, debug=debug)
        if ffprobeResult == 0:
            ffprobeOutput = mmguero.LoadStrIfJson(' '.join(ffprobeOutput))
            if 'streams' in ffprobeOutput:
                for stream in ffprobeOutput['streams']:
                    if 'codec_name' in stream and 'codec_type' in stream:
                        cType = stream['codec_type'].lower()
                        cValue = stream['codec_name'].lower()
                        if cType in result:
                            result[cType].add(cValue)
                        else:
                            result[cType] = set([cValue])
            result['format'] = mmguero.DeepGet(ffprobeOutput, ['format', 'format_name'])
            if isinstance(result['format'], str):
                result['format'] = result['format'].split(',')
        else:
            mmguero.eprint(' '.join(mmguero.Flatten(ffprobeCmd)))
            mmguero.eprint(ffprobeResult)
            mmguero.eprint(ffprobeOutput)
            raise ValueError(f"Could not analyze {local_filename}")

    return result


#################################################################################
class Plugger(object):
    debug = False
    inputFileSpec = ""
    inputCodecs = {}
    inputFileParts = None
    outputFileSpec = ""
    outputAudioFileFormat = ""
    outputVideoFileFormat = ""
    outputJson = ""
    tmpDownloadedFileSpec = ""
    swearsFileSpec = ""
    swearsMap = {}
    wordList = []
    naughtyWordList = []
    # for beep and mute
    muteTimeList = []
    # for beep only
    sineTimeList = []
    beepDelayList = []
    padSecPre = 0.0
    padSecPost = 0.0
    beep = False
    beepHertz = BEEP_HERTZ_DEFAULT
    forceDespiteTag = False
    aParams = None
    tags = None

    ######## init #################################################################
    def __init__(
        self,
        iFileSpec,
        oFileSpec,
        oAudioFileFormat,
        iSwearsFileSpec,
        outputJson,
        aParams=None,
        aChannels=AUDIO_DEFAULT_CHANNELS,
        padMsecPre=0,
        padMsecPost=0,
        beep=False,
        beepHertz=BEEP_HERTZ_DEFAULT,
        force=False,
        dbug=False,
    ):
        self.padSecPre = padMsecPre / 1000.0
        self.padSecPost = padMsecPost / 1000.0
        self.beep = beep
        self.beepHertz = beepHertz
        self.forceDespiteTag = force
        self.debug = dbug
        self.outputJson = outputJson

        # determine input file name, or download and save file
        if (iFileSpec is not None) and os.path.isfile(iFileSpec):
            self.inputFileSpec = iFileSpec
        elif iFileSpec.lower().startswith("http"):
            self.tmpDownloadedFileSpec = DownloadToFile(iFileSpec)
            if (self.tmpDownloadedFileSpec is not None) and os.path.isfile(self.tmpDownloadedFileSpec):
                self.inputFileSpec = self.tmpDownloadedFileSpec
            else:
                raise IOError(errno.ENOENT, os.strerror(errno.ENOENT), iFileSpec)
        else:
            raise IOError(errno.ENOENT, os.strerror(errno.ENOENT), iFileSpec)

        # input file should exist locally by now
        if os.path.isfile(self.inputFileSpec):
            self.inputFileParts = os.path.splitext(self.inputFileSpec)
            self.inputCodecs = GetCodecs(self.inputFileSpec)
            inputFormat = next(
                iter([x for x in self.inputCodecs.get('format', None) if x in AUDIO_DEFAULT_PARAMS_BY_FORMAT]), None
            )
        else:
            raise IOError(errno.ENOENT, os.strerror(errno.ENOENT), self.inputFileSpec)

        # determine output file name (either specified or based on input filename)
        self.outputFileSpec = oFileSpec if oFileSpec else self.inputFileParts[0] + "_clean"
        if self.outputFileSpec:
            outParts = os.path.splitext(self.outputFileSpec)
            if not oAudioFileFormat:
                oAudioFileFormat = outParts[1]

        if str(oAudioFileFormat).upper() == AUDIO_MATCH_FORMAT:
            # output format not specified, base on input filename matching extension (or codec)
            if self.inputFileParts[1] in AUDIO_DEFAULT_PARAMS_BY_FORMAT:
                self.outputFileSpec = self.outputFileSpec + self.inputFileParts[1]
            elif str(inputFormat).lower() in AUDIO_DEFAULT_PARAMS_BY_FORMAT:
                self.outputFileSpec = self.outputFileSpec + '.' + inputFormat.lower()
            else:
                for codec in mmguero.GetIterable(self.inputCodecs.get('audio', [])):
                    if codec.lower() in AUDIO_CODEC_TO_FORMAT:
                        self.outputFileSpec = self.outputFileSpec + '.' + AUDIO_CODEC_TO_FORMAT[codec.lower()]
                        break

        elif oAudioFileFormat:
            # output filename not specified, base on input filename with specified format
            self.outputFileSpec = self.outputFileSpec + '.' + oAudioFileFormat.lower().lstrip('.')

        else:
            # can't determine what output file audio format should be
            raise ValueError("Output file audio format unspecified")

        # determine output file extension if it's not already obvious
        outParts = os.path.splitext(self.outputFileSpec)
        self.outputAudioFileFormat = outParts[1].lower().lstrip('.')

        if (not self.outputAudioFileFormat) or (
            (not aParams) and (self.outputAudioFileFormat not in AUDIO_DEFAULT_PARAMS_BY_FORMAT)
        ):
            raise ValueError("Output file audio format unspecified or unsupported")
        elif not aParams:
            # we're using ffmpeg encoding params based on output file format
            self.aParams = AUDIO_DEFAULT_PARAMS_BY_FORMAT[self.outputAudioFileFormat]
        else:
            # they specified custom ffmpeg encoding params
            self.aParams = aParams
            if self.aParams.startswith("base64:"):
                self.aParams = base64.b64decode(self.aParams[7:]).decode("utf-8")
            self.aParams = self.aParams.split(' ')
        self.aParams = [str(aChannels) if aParam == CHANNELS_REPLACER else aParam for aParam in self.aParams]

        # if we're actually just replacing the audio stream(s) inside a video file, the actual output file is still a video file
        self.outputVideoFileFormat = (
            self.inputFileParts[1]
            if (
                (len(mmguero.GetIterable(self.inputCodecs.get('video', []))) > 0)
                and (str(oAudioFileFormat).upper() == AUDIO_MATCH_FORMAT)
            )
            else ''
        )
        if self.outputVideoFileFormat:
            self.outputFileSpec = outParts[0] + self.outputVideoFileFormat

        # if output file already exists, remove as we'll be overwriting it anyway
        if os.path.isfile(self.outputFileSpec):
            if self.debug:
                mmguero.eprint(f'Removing existing destination file {self.outputFileSpec}')
            os.remove(self.outputFileSpec)

        # load the swears file (not actually mapping right now, but who knows, speech synthesis maybe someday?)
        if (iSwearsFileSpec is not None) and os.path.isfile(iSwearsFileSpec):
            self.swearsFileSpec = iSwearsFileSpec
        else:
            raise IOError(errno.ENOENT, os.strerror(errno.ENOENT), iSwearsFileSpec)
        lines = []
        with open(self.swearsFileSpec) as f:
            lines = [line.rstrip("\n") for line in f]
        for line in lines:
            lineMap = line.split("|")
            self.swearsMap[scrubword(lineMap[0])] = lineMap[1] if len(lineMap) > 1 else "*****"

        if self.debug:
            mmguero.eprint(f'Input: {self.inputFileSpec}')
            mmguero.eprint(f'Input codec: {self.inputCodecs}')
            mmguero.eprint(f'Output: {self.outputFileSpec}')
            mmguero.eprint(f'Output audio format: {self.outputAudioFileFormat}')
            mmguero.eprint(f'Encode parameters: {self.aParams}')
            mmguero.eprint(f'Profanity file: {self.swearsFileSpec}')
            mmguero.eprint(f'Intermediate downloaded file: {self.tmpDownloadedFileSpec}')
            mmguero.eprint(f'Beep instead of mute: {self.beep}')
            mmguero.eprint(f'Beep hertz: {self.beepHertz}')
            mmguero.eprint(f'Force despite tags: {self.forceDespiteTag}')

    ######## del ##################################################################
    def __del__(self):
        # if we downloaded the input file, remove it as well
        if os.path.isfile(self.tmpDownloadedFileSpec):
            os.remove(self.tmpDownloadedFileSpec)

    ######## CreateCleanMuteList #################################################
    def CreateCleanMuteList(self):
        self.RecognizeSpeech()

        self.naughtyWordList = [word for word in self.wordList if word["scrub"] is True]
        if len(self.naughtyWordList) > 0:
            # append a dummy word at the very end so that pairwise can peek then ignore it
            self.naughtyWordList.extend(
                [
                    {
                        "conf": 1,
                        "end": self.naughtyWordList[-1]["end"] + 2.0,
                        "start": self.naughtyWordList[-1]["end"] + 1.0,
                        "word": "mothaflippin",
                        "scrub": True,
                    }
                ]
            )
        if self.debug:
            mmguero.eprint(self.naughtyWordList)

        self.muteTimeList = []
        self.sineTimeList = []
        self.beepDelayList = []
        for word, wordPeek in pairwise(self.naughtyWordList):
            wordStart = format(word["start"] - self.padSecPre, ".3f")
            wordEnd = format(word["end"] + self.padSecPost, ".3f")
            wordDuration = format(float(wordEnd) - float(wordStart), ".3f")
            wordPeekStart = format(wordPeek["start"] - self.padSecPre, ".3f")
            if self.beep:
                self.muteTimeList.append(f"volume=enable='between(t,{wordStart},{wordEnd})':volume=0")
                self.sineTimeList.append(f"sine=f={self.beepHertz}:duration={wordDuration}")
                self.beepDelayList.append(
                    f"atrim=0:{wordDuration},adelay={'|'.join([str(int(float(wordStart) * 1000))] * 2)}"
                )
            else:
                self.muteTimeList.append(
                    "afade=enable='between(t," + wordStart + "," + wordEnd + ")':t=out:st=" + wordStart + ":d=5ms"
                )
                self.muteTimeList.append(
                    "afade=enable='between(t," + wordEnd + "," + wordPeekStart + ")':t=in:st=" + wordEnd + ":d=5ms"
                )

        if self.debug:
            mmguero.eprint(self.muteTimeList)
            if self.beep:
                mmguero.eprint(self.sineTimeList)
                mmguero.eprint(self.beepDelayList)

        return self.muteTimeList

    ######## EncodeCleanAudio ####################################################
    def EncodeCleanAudio(self):
        if (self.forceDespiteTag is True) or (GetMonkeyplugTagged(self.inputFileSpec, debug=self.debug) is False):
            self.CreateCleanMuteList()

            if len(self.muteTimeList) > 0:
                if self.beep:
                    muteTimeListStr = ','.join(self.muteTimeList)
                    sineTimeListStr = ';'.join([f'{val}[beep{i+1}]' for i, val in enumerate(self.sineTimeList)])
                    beepDelayList = ';'.join(
                        [f'[beep{i+1}]{val}[beep{i+1}_delayed]' for i, val in enumerate(self.beepDelayList)]
                    )
                    beepMixList = ''.join([f'[beep{i+1}_delayed]' for i in range(len(self.beepDelayList))])
                    filterStr = f"[0:a]{muteTimeListStr}[mute];{sineTimeListStr};{beepDelayList};[mute]{beepMixList}amix=inputs={len(self.beepDelayList)+1}"
                    audioArgs = ['-filter_complex', filterStr]
                else:
                    audioArgs = ['-af', ",".join(self.muteTimeList)]
            else:
                audioArgs = []

            if self.outputVideoFileFormat:
                # replace existing audio stream in video file with -copy
                ffmpegCmd = [
                    'ffmpeg',
                    '-nostdin',
                    '-hide_banner',
                    '-nostats',
                    '-loglevel',
                    'error',
                    '-y',
                    '-i',
                    self.inputFileSpec,
                    '-c:v',
                    'copy',
                    '-sn',
                    '-dn',
                    audioArgs,
                    self.aParams,
                    self.outputFileSpec,
                ]

            else:
                ffmpegCmd = [
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
                    audioArgs,
                    self.aParams,
                    self.outputFileSpec,
                ]
            ffmpegResult, ffmpegOutput = mmguero.RunProcess(ffmpegCmd, stdout=True, stderr=True, debug=self.debug)
            if (ffmpegResult != 0) or (not os.path.isfile(self.outputFileSpec)):
                mmguero.eprint(' '.join(mmguero.Flatten(ffmpegCmd)))
                mmguero.eprint(ffmpegResult)
                mmguero.eprint(ffmpegOutput)
                raise ValueError(f"Could not process {self.inputFileSpec}")

            SetMonkeyplugTag(self.outputFileSpec, debug=self.debug)

        else:
            shutil.copyfile(self.inputFileSpec, self.outputFileSpec)

        return self.outputFileSpec


#################################################################################


#################################################################################
class VoskPlugger(Plugger):
    tmpWavFileSpec = ""
    modelPath = ""
    wavReadFramesChunk = AUDIO_DEFAULT_WAV_FRAMES_CHUNK
    vosk = None

    def __init__(
        self,
        iFileSpec,
        oFileSpec,
        oAudioFileFormat,
        iSwearsFileSpec,
        mDir,
        outputJson,
        aParams=None,
        aChannels=AUDIO_DEFAULT_CHANNELS,
        wChunk=AUDIO_DEFAULT_WAV_FRAMES_CHUNK,
        padMsecPre=0,
        padMsecPost=0,
        beep=False,
        beepHertz=BEEP_HERTZ_DEFAULT,
        force=False,
        dbug=False,
    ):
        self.wavReadFramesChunk = wChunk

        # make sure the VOSK model path exists
        if (mDir is not None) and os.path.isdir(mDir):
            self.modelPath = mDir
        else:
            raise IOError(
                errno.ENOENT,
                os.strerror(errno.ENOENT) + " (see https://alphacephei.com/vosk/models)",
                mDir,
            )

        self.vosk = mmguero.DoDynamicImport("vosk", "vosk", debug=dbug)
        if not self.vosk:
            raise Exception(f"Unable to initialize VOSK API")
        if not dbug:
            self.vosk.SetLogLevel(-1)

        super().__init__(
            iFileSpec=iFileSpec,
            oFileSpec=oFileSpec,
            oAudioFileFormat=oAudioFileFormat,
            iSwearsFileSpec=iSwearsFileSpec,
            outputJson=outputJson,
            aParams=aParams,
            aChannels=aChannels,
            padMsecPre=padMsecPre,
            padMsecPost=padMsecPost,
            beep=beep,
            beepHertz=beepHertz,
            force=force,
            dbug=dbug,
        )

        self.tmpWavFileSpec = self.inputFileParts[0] + ".wav"

        if self.debug:
            mmguero.eprint(f'Model directory: {self.modelPath}')
            mmguero.eprint(f'Intermediate audio file: {self.tmpWavFileSpec}')
            mmguero.eprint(f'Read frames: {self.wavReadFramesChunk}')

    def __del__(self):
        super().__del__()
        # clean up intermediate WAV file used for speech recognition
        if os.path.isfile(self.tmpWavFileSpec):
            os.remove(self.tmpWavFileSpec)

    def CreateIntermediateWAV(self):
        ffmpegCmd = [
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
            AUDIO_INTERMEDIATE_PARAMS,
            self.tmpWavFileSpec,
        ]
        ffmpegResult, ffmpegOutput = mmguero.RunProcess(ffmpegCmd, stdout=True, stderr=True, debug=self.debug)
        if (ffmpegResult != 0) or (not os.path.isfile(self.tmpWavFileSpec)):
            mmguero.eprint(' '.join(mmguero.Flatten(ffmpegCmd)))
            mmguero.eprint(ffmpegResult)
            mmguero.eprint(ffmpegOutput)
            raise ValueError(
                f"Could not convert {self.inputFileSpec} to {self.tmpWavFileSpec} (16 kHz, mono, s16 PCM WAV)"
            )

        return self.inputFileSpec

    def RecognizeSpeech(self):
        self.CreateIntermediateWAV()
        self.wordList.clear()
        with wave.open(self.tmpWavFileSpec, "rb") as wf:
            if (
                (wf.getnchannels() != 1)
                or (wf.getframerate() != 16000)
                or (wf.getsampwidth() != 2)
                or (wf.getcomptype() != "NONE")
            ):
                raise Exception(f"Audio file ({self.tmpWavFileSpec}) must be 16 kHz, mono, s16 PCM WAV")

            rec = self.vosk.KaldiRecognizer(self.vosk.Model(self.modelPath), wf.getframerate())
            rec.SetWords(True)
            while True:
                data = wf.readframes(self.wavReadFramesChunk)
                if len(data) == 0:
                    break
                if rec.AcceptWaveform(data):
                    res = json.loads(rec.Result())
                    if "result" in res:
                        self.wordList.extend(
                            [
                                dict(r, **{'scrub': scrubword(mmguero.DeepGet(r, ["word"])) in self.swearsMap})
                                for r in res["result"]
                            ]
                        )
            res = json.loads(rec.FinalResult())
            if "result" in res:
                self.wordList.extend(
                    [
                        dict(r, **{'scrub': scrubword(mmguero.DeepGet(r, ["word"])) in self.swearsMap})
                        for r in res["result"]
                    ]
                )

            if self.debug:
                mmguero.eprint(json.dumps(self.wordList))

            if self.outputJson:
                with open(self.outputJson, "w") as f:
                    f.write(json.dumps(self.wordList))

        return self.wordList


#################################################################################


#################################################################################
class WhisperPlugger(Plugger):
    debug = False
    model = None
    whisper = None
    transcript = None

    def __init__(
        self,
        iFileSpec,
        oFileSpec,
        oAudioFileFormat,
        iSwearsFileSpec,
        mDir,
        mName,
        outputJson,
        aParams=None,
        aChannels=AUDIO_DEFAULT_CHANNELS,
        padMsecPre=0,
        padMsecPost=0,
        beep=False,
        beepHertz=BEEP_HERTZ_DEFAULT,
        force=False,
        dbug=False,
    ):
        self.whisper = mmguero.DoDynamicImport("whisper", "openai-whisper", debug=dbug)
        if not self.whisper:
            raise Exception("Unable to initialize Whisper API")

        self.model = self.whisper.load_model(mName, download_root=mDir)
        if not self.model:
            raise Exception(f"Unable to load Whisper model {mName} in {mDir}")

        super().__init__(
            iFileSpec=iFileSpec,
            oFileSpec=oFileSpec,
            oAudioFileFormat=oAudioFileFormat,
            iSwearsFileSpec=iSwearsFileSpec,
            outputJson=outputJson,
            aParams=aParams,
            aChannels=aChannels,
            padMsecPre=padMsecPre,
            padMsecPost=padMsecPost,
            beep=beep,
            beepHertz=beepHertz,
            force=force,
            dbug=dbug,
        )

        if self.debug:
            mmguero.eprint(f'Model directory: {mDir}')
            mmguero.eprint(f'Model name: {mName}')

    def __del__(self):
        super().__del__()

    def RecognizeSpeech(self):
        self.wordList.clear()

        self.transcript = self.model.transcribe(word_timestamps=True, audio=self.inputFileSpec)
        if self.transcript and ('segments' in self.transcript):
            for segment in self.transcript['segments']:
                if 'words' in segment:
                    for word in segment['words']:
                        word['word'] = word['word'].strip()
                        word['scrub'] = scrubword(word['word']) in self.swearsMap
                        self.wordList.append(word)

        if self.debug:
            mmguero.eprint(json.dumps(self.wordList))

        if self.outputJson:
            with open(self.outputJson, "w") as f:
                f.write(json.dumps(self.wordList))

        return self.wordList


#################################################################################


###################################################################################################
# RunMonkeyPlug
def RunMonkeyPlug():
    parser = argparse.ArgumentParser(
        description=script_name,
        add_help=False,
        usage="{} <arguments>".format(script_name),
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
        "-a",
        "--audio-params",
        help=f"Audio parameters for ffmpeg (default depends on output audio codec)",
        dest="aParams",
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
        help=f"Milliseconds to pad on either side of muted segments (default: 0)",
    )
    parser.add_argument(
        "--pad-milliseconds-pre",
        dest="padMsecPre",
        metavar="<int>",
        type=int,
        default=0,
        help=f"Milliseconds to pad before muted segments (default: 0)",
    )
    parser.add_argument(
        "--pad-milliseconds-post",
        dest="padMsecPost",
        metavar="<int>",
        type=int,
        default=0,
        help=f"Milliseconds to pad after muted segments (default: 0)",
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
        "-h",
        "--beep-hertz",
        dest="beepHertz",
        metavar="<int>",
        type=int,
        default=BEEP_HERTZ_DEFAULT,
        help=f"Beep frequency hertz (default: {BEEP_HERTZ_DEFAULT})",
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
        default=os.getenv("VOSK_READ_FRAMES", AUDIO_DEFAULT_WAV_FRAMES_CHUNK),
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

    try:
        parser.error = parser.exit
        args = parser.parse_args()
    except SystemExit as sy:
        mmguero.eprint(sy)
        parser.print_help()
        exit(2)

    if args.debug:
        mmguero.eprint(os.path.join(script_path, script_name))
        mmguero.eprint("Arguments: {}".format(sys.argv[1:]))
        mmguero.eprint("Arguments: {}".format(args))
    else:
        sys.tracebacklimit = 0

    if args.speechRecMode == SPEECH_REC_MODE_VOSK:
        pathlib.Path(args.voskModelDir).mkdir(parents=True, exist_ok=True)
        plug = VoskPlugger(
            args.input,
            args.output,
            args.outputFormat,
            args.swears,
            args.voskModelDir,
            args.outputJson,
            aParams=args.aParams,
            aChannels=args.aChannels,
            wChunk=args.voskReadFramesChunk,
            padMsecPre=args.padMsecPre if args.padMsecPre > 0 else args.padMsec,
            padMsecPost=args.padMsecPost if args.padMsecPost > 0 else args.padMsec,
            beep=args.beep,
            beepHertz=args.beepHertz,
            force=args.forceDespiteTag,
            dbug=args.debug,
        )

    elif args.speechRecMode == SPEECH_REC_MODE_WHISPER:
        pathlib.Path(args.whisperModelDir).mkdir(parents=True, exist_ok=True)
        plug = WhisperPlugger(
            args.input,
            args.output,
            args.outputFormat,
            args.swears,
            args.whisperModelDir,
            args.whisperModelName,
            args.outputJson,
            aParams=args.aParams,
            aChannels=args.aChannels,
            padMsecPre=args.padMsecPre if args.padMsecPre > 0 else args.padMsec,
            padMsecPost=args.padMsecPost if args.padMsecPost > 0 else args.padMsec,
            beep=args.beep,
            beepHertz=args.beepHertz,
            force=args.forceDespiteTag,
            dbug=args.debug,
        )
    else:
        raise ValueError(f"Unsupported speech recognition engine {args.speechRecMode}")

    print(plug.EncodeCleanAudio())


###################################################################################################
if __name__ == "__main__":
    RunMonkeyPlug()
