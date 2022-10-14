#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import delegator
import errno
import json
import mmguero
import mutagen
import os
import requests
import sys
import vosk
import wave

from urllib.parse import urlparse

###################################################################################################
AUDIO_DEFAULT_PARAMS_BY_FORMAT = {
    "flac": ["-c:a", "flac", "-ar", "44100", "-ac", "2"],
    "m4a": ["-c:a", "aac", "-b:a", "128K", "-ar", "44100", "-ac", "2"],
    "aac": ["-c:a", "aac", "-b:a", "128K", "-ar", "44100", "-ac", "2"],
    "mp3": ["-c:a", "libmp3lame", "-b:a", "128K", "-ar", "44100", "-ac", "2"],
    "ogg": ["-c:a", "libvorbis", "-qscale:a", "5", "-ar", "44100", "-ac", "2"],
    "opus": ["-c:a", "libopus", "-b:a", "128K", "-ar", "48000", "-ac", "2"],
    "ac3": ["-c:a", "ac3", "-b:a", "128K", "-ar", "44100", "-ac", "2"],
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
AUDIO_MATCH_FORMAT = "MATCH"
AUDIO_INTERMEDIATE_PARAMS = ["-c:a", "pcm_s16le", "-ac", "1", "-ar", "16000"]
AUDIO_DEFAULT_WAV_FRAMES_CHUNK = 8000
SWEARS_FILENAME_DEFAULT = 'swears.txt'
MUTAGEN_METADATA_TAGS = ['encodedby', 'comment']
MUTAGEN_METADATA_TAG_VALUE = u'monkeyplug'

###################################################################################################
script_name = os.path.basename(__file__)
script_path = os.path.dirname(os.path.realpath(__file__))


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
    outputFileSpec = ""
    outputAudioFileFormat = ""
    outputVideoFileFormat = ""
    outputJson = ""
    tmpWavFileSpec = ""
    tmpDownloadedFileSpec = ""
    swearsFileSpec = ""
    swearsMap = {}
    wordList = []
    naughtyWordList = []
    muteTimeList = []
    modelPath = ""
    wavReadFramesChunk = AUDIO_DEFAULT_WAV_FRAMES_CHUNK
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
        mPath,
        outputJson,
        aParams=None,
        wChunk=AUDIO_DEFAULT_WAV_FRAMES_CHUNK,
        force=False,
        dbug=False,
    ):
        self.wavReadFramesChunk = wChunk
        self.forceDespiteTag = force
        self.debug = dbug
        self.outputJson = outputJson

        # make sure the VOSK model path exists
        if (mPath is not None) and os.path.isdir(mPath):
            self.modelPath = mPath
        else:
            raise IOError(
                errno.ENOENT,
                os.strerror(errno.ENOENT) + " (see https://alphacephei.com/vosk/models)",
                mPath,
            )

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
            inParts = os.path.splitext(self.inputFileSpec)
            self.inputCodecs = GetCodecs(self.inputFileSpec)
            inputFormat = next(
                iter([x for x in self.inputCodecs.get('format', None) if x in AUDIO_DEFAULT_PARAMS_BY_FORMAT]), None
            )
        else:
            raise IOError(errno.ENOENT, os.strerror(errno.ENOENT), self.inputFileSpec)

        # determine output file name (either specified or based on input filename)
        self.outputFileSpec = oFileSpec if oFileSpec else inParts[0] + "_clean"
        if self.outputFileSpec:
            outParts = os.path.splitext(self.outputFileSpec)
            if not oAudioFileFormat:
                oAudioFileFormat = outParts[1]

        if str(oAudioFileFormat).upper() == AUDIO_MATCH_FORMAT:
            # output format not specified, base on input filename matching extension (or codec)
            if inParts[1] in AUDIO_DEFAULT_PARAMS_BY_FORMAT:
                self.outputFileSpec = self.outputFileSpec + inParts[1]
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
                self.aParams = base64.b64decode(self.aParams[7:]).decode("utf-8").split(' ')

        # if we're actually just replacing the audio stream(s) inside a video file, the actual output file is still a video file
        self.outputVideoFileFormat = (
            inParts[1]
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

        self.tmpWavFileSpec = inParts[0] + ".wav"

        # load the swears file (not actually mapping right now, but who knows, speech synthesis maybe someday?)
        if (iSwearsFileSpec is not None) and os.path.isfile(iSwearsFileSpec):
            self.swearsFileSpec = iSwearsFileSpec
        else:
            raise IOError(errno.ENOENT, os.strerror(errno.ENOENT), iSwearsFileSpec)
        lines = []
        with open(self.swearsFileSpec) as f:
            lines = [line.rstrip("\n").lower() for line in f]
        for line in lines:
            lineMap = line.split("|")
            if len(lineMap) > 1:
                self.swearsMap[lineMap[0]] = lineMap[1]
            else:
                self.swearsMap[lineMap[0]] = "*****"

        if self.debug:
            mmguero.eprint(f'Input: {self.inputFileSpec}')
            mmguero.eprint(f'Input codec: {self.inputCodecs}')
            mmguero.eprint(f'Output: {self.outputFileSpec}')
            mmguero.eprint(f'Output audio format: {self.outputAudioFileFormat}')
            mmguero.eprint(f'Encode parameters: {self.aParams}')
            mmguero.eprint(f'Profanity file: {self.swearsFileSpec}')
            mmguero.eprint(f'Intermediate audio file: {self.tmpWavFileSpec}')
            mmguero.eprint(f'Intermediate downloaded file: {self.tmpDownloadedFileSpec}')
            mmguero.eprint(f'Read frames: {self.wavReadFramesChunk}')
            mmguero.eprint(f'Force despite tags: {self.forceDespiteTag}')

    ######## del ##################################################################
    def __del__(self):
        # clean up intermediate WAV file used for speech recognition
        if os.path.isfile(self.tmpWavFileSpec):
            os.remove(self.tmpWavFileSpec)

        # if we downloaded the input file, remove it as well
        if os.path.isfile(self.tmpDownloadedFileSpec):
            os.remove(self.tmpDownloadedFileSpec)

    ######## CreateIntermediateWAV ###############################################
    def CreateIntermediateWAV(self):
        ffmpegCmd = [
            'ffmpeg',
            '-nostdin',
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

    ######## CreateIntermediateWAV ###############################################
    def RecognizeSpeech(self):
        self.wordList.clear()
        with wave.open(self.tmpWavFileSpec, "rb") as wf:
            if (
                (wf.getnchannels() != 1)
                or (wf.getframerate() != 16000)
                or (wf.getsampwidth() != 2)
                or (wf.getcomptype() != "NONE")
            ):
                raise Exception(f"Audio file ({self.tmpWavFileSpec}) must be 16 kHz, mono, s16 PCM WAV")

            rec = vosk.KaldiRecognizer(vosk.Model(self.modelPath), wf.getframerate())
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
                                dict(r, **{'scrub': mmguero.DeepGet(r, ["word"]) in self.swearsMap})
                                for r in res["result"]
                            ]
                        )
            res = json.loads(rec.FinalResult())
            if "result" in res:
                self.wordList.extend(
                    [dict(r, **{'scrub': mmguero.DeepGet(r, ["word"]) in self.swearsMap}) for r in res["result"]]
                )

            if self.debug:
                mmguero.eprint(json.dumps(self.wordList))

            if self.outputJson:
                with open(self.outputJson, "w") as f:
                    f.write(json.dumps(self.wordList))

        return self.wordList

    ######## CreateCleanMuteList #################################################
    def CreateCleanMuteList(self):
        self.CreateIntermediateWAV()
        self.RecognizeSpeech()

        self.naughtyWordList = [word for word in self.wordList if word["scrub"] is True]
        if self.debug:
            mmguero.eprint(self.naughtyWordList)

        self.muteTimeList = [
            "volume=enable='between(t,"
            + format(word["start"], ".3f")
            + ","
            + format(word["end"], ".3f")
            + ")':volume=0"
            for word in self.naughtyWordList
        ]
        if self.debug:
            mmguero.eprint(self.muteTimeList)

        return self.muteTimeList

    ######## EncodeCleanAudio ####################################################
    def EncodeCleanAudio(self):
        if (self.forceDespiteTag is True) or (GetMonkeyplugTagged(self.inputFileSpec, debug=self.debug) is False):
            self.CreateCleanMuteList()

            if len(self.muteTimeList) > 0:
                audioArgs = ['-af', ",".join(self.muteTimeList)]
            else:
                audioArgs = []

            if self.outputVideoFileFormat:
                # replace existing audio stream in video file with -copy
                ffmpegCmd = [
                    'ffmpeg',
                    '-nostdin',
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
            if (ffmpegResult != 0) or (not os.path.isfile(self.tmpWavFileSpec)):
                mmguero.eprint(' '.join(mmguero.Flatten(ffmpegCmd)))
                mmguero.eprint(ffmpegResult)
                mmguero.eprint(ffmpegOutput)
                raise ValueError(f"Could not process {self.inputFileSpec}")

            SetMonkeyplugTag(self.outputFileSpec, debug=self.debug)
            return self.outputFileSpec

        else:
            return self.inputFileSpec


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
        help="Output file to store JSON generated by VOSK",
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
        help=f"Audio parameters for ffmpeg (default depends on output audio codec\")",
        dest="aParams",
        default=None,
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
        "-m",
        "--model",
        dest="modelPath",
        metavar="<string>",
        type=str,
        default=os.getenv("VOSK_MODEL", os.path.join(script_path, "model")),
        help="Vosk model path (default: \"model\")",
    )
    parser.add_argument(
        "--frames",
        dest="readFramesChunk",
        metavar="<int>",
        type=int,
        default=os.getenv("VOSK_READ_FRAMES", AUDIO_DEFAULT_WAV_FRAMES_CHUNK),
        help=f"WAV frame chunk (default: {AUDIO_DEFAULT_WAV_FRAMES_CHUNK})",
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

    try:
        parser.error = parser.exit
        args = parser.parse_args()
    except SystemExit:
        parser.print_help()
        exit(2)

    if args.debug:
        mmguero.eprint(os.path.join(script_path, script_name))
        mmguero.eprint("Arguments: {}".format(sys.argv[1:]))
        mmguero.eprint("Arguments: {}".format(args))
    else:
        sys.tracebacklimit = 0
        vosk.SetLogLevel(-1)

    print(
        Plugger(
            args.input,
            args.output,
            args.outputFormat,
            args.swears,
            args.modelPath,
            args.outputJson,
            aParams=args.aParams,
            wChunk=args.readFramesChunk,
            force=args.forceDespiteTag,
            dbug=args.debug,
        ).EncodeCleanAudio()
    )


###################################################################################################
if __name__ == "__main__":
    RunMonkeyPlug()
