#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import delegator
import errno
import json
import os
import requests
import sys
import wave
import vosk

from urllib.parse import urlparse

###################################################################################################
AUDIO_DEFAULT_PARAMS = "-c:a libmp3lame -ab 96k -ar 44100 -ac 2"
AUDIO_DEFAULT_EXTENSION = "mp3"
AUDIO_INTERMEDIATE_PARAMS = "-c:a pcm_s16le -ac 1 -ar 16000"
AUDIO_DEFAULT_WAV_FRAMES_CHUNK = 8000
SWEARS_FILENAME_DEFAULT = 'swears.txt'

###################################################################################################
script_name = os.path.basename(__file__)
script_path = os.path.dirname(os.path.realpath(__file__))

###################################################################################################
# print to stderr
def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)
    sys.stderr.flush()


###################################################################################################
# convenient boolean argument parsing
def str2bool(v):
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    elif v.lower() in ("no", "false", "f", "n", "0"):
        return False
    else:
        raise ValueError("Boolean value expected")


###################################################################################################
# nice human-readable file sizes
def SizeHumanFormat(num, suffix="B"):
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}{'Yi'}{suffix}"


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
        eprint(
            f"Download of {url} to {tmpDownloadedFileSpec} {'succeeded' if fExists else 'failed'} ({SizeHumanFormat(fSize)})"
        )

    if fExists and (fSize > 0):
        return tmpDownloadedFileSpec
    else:
        if fExists:
            os.remove(tmpDownloadedFileSpec)
        return None


#################################################################################
class Plugger(object):
    debug = False
    inputAudioFileSpec = ""
    outputAudioFileSpec = ""
    tmpWavFileSpec = ""
    tmpDownloadedFileSpec = ""
    swearsFileSpec = ""
    swearsMap = {}
    wordList = []
    naughtyWordList = []
    muteTimeList = []
    modelPath = ""
    wavReadFramesChunk = AUDIO_DEFAULT_WAV_FRAMES_CHUNK
    aParams = AUDIO_DEFAULT_PARAMS

    ######## init #################################################################
    def __init__(
        self,
        iAudioFileSpec,
        oAudioFileSpec,
        iSwearsFileSpec,
        mPath,
        aParams=AUDIO_DEFAULT_PARAMS,
        wChunk=AUDIO_DEFAULT_WAV_FRAMES_CHUNK,
        dbug=False,
    ):
        self.wavReadFramesChunk = wChunk
        self.debug = dbug

        if (mPath is not None) and os.path.isdir(mPath):
            self.modelPath = mPath
        else:
            raise IOError(
                errno.ENOENT,
                os.strerror(errno.ENOENT) + " (see https://alphacephei.com/vosk/models)",
                mPath,
            )

        if (iAudioFileSpec is not None) and os.path.isfile(iAudioFileSpec):
            self.inputAudioFileSpec = iAudioFileSpec
        elif iAudioFileSpec.lower().startswith("http"):
            self.tmpDownloadedFileSpec = DownloadToFile(iAudioFileSpec)
            if (self.tmpDownloadedFileSpec is not None) and os.path.isfile(self.tmpDownloadedFileSpec):
                self.inputAudioFileSpec = self.tmpDownloadedFileSpec
            else:
                raise IOError(errno.ENOENT, os.strerror(errno.ENOENT), iAudioFileSpec)
        else:
            raise IOError(errno.ENOENT, os.strerror(errno.ENOENT), iAudioFileSpec)

        if (oAudioFileSpec is not None) and (len(oAudioFileSpec) > 0):
            self.outputAudioFileSpec = oAudioFileSpec
            if os.path.isfile(self.outputAudioFileSpec):
                os.remove(self.outputAudioFileSpec)

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

        # if they specified custom ffmpeg encoding params
        self.aParams = aParams
        if self.aParams.startswith("base64:"):
            self.aParams = base64.b64decode(self.aParams[7:]).decode("utf-8")

    ######## del ##################################################################
    def __del__(self):
        # clean up intermediate WAV file used for speech recognition
        if os.path.isfile(self.tmpWavFileSpec):
            os.remove(self.tmpWavFileSpec)

        # if we downloaded the audio file, remove it as well
        if os.path.isfile(self.tmpDownloadedFileSpec):
            os.remove(self.tmpDownloadedFileSpec)

    ######## CreateIntermediateWAV ###############################################
    def CreateIntermediateWAV(self):
        audioFileParts = os.path.splitext(self.inputAudioFileSpec)
        self.tmpWavFileSpec = audioFileParts[0] + ".wav"
        ffmpegCmd = (
            'ffmpeg -y -i "'
            + self.inputAudioFileSpec
            + '" '
            + AUDIO_INTERMEDIATE_PARAMS
            + ' "'
            + self.tmpWavFileSpec
            + '"'
        )
        ffmpegResult = delegator.run(ffmpegCmd, block=True)
        if (ffmpegResult.return_code != 0) or (not os.path.isfile(self.tmpWavFileSpec)):
            print(ffmpegCmd)
            print(ffmpegResult.err)
            raise ValueError(
                f"Could not convert {self.inputAudioFileSpec} to {self.tmpWavFileSpec} (16 kHz, mono, s16 PCM WAV)"
            )

        return self.inputAudioFileSpec

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
                        self.wordList.extend(res["result"])

            res = json.loads(rec.FinalResult())
            if "result" in res:
                self.wordList.extend(res["result"])

            if self.debug:
                eprint(json.dumps(self.wordList))

        return self.wordList

    ######## CreateCleanMuteList #################################################
    def CreateCleanMuteList(self):
        self.CreateIntermediateWAV()
        self.RecognizeSpeech()

        self.naughtyWordList = [word for word in self.wordList if (word["word"].lower() in self.swearsMap)]
        if self.debug:
            eprint(self.naughtyWordList)

        self.muteTimeList = [
            "volume=enable='between(t,"
            + format(word["start"], ".3f")
            + ","
            + format(word["end"], ".3f")
            + ")':volume=0"
            for word in self.naughtyWordList
        ]
        if self.debug:
            eprint(self.muteTimeList)

        return self.muteTimeList

    ######## EncodeCleanAudio ####################################################
    def EncodeCleanAudio(self):
        self.CreateCleanMuteList()

        if len(self.muteTimeList) > 0:
            audioArgs = ' -af "' + ",".join(self.muteTimeList) + '" '
        else:
            audioArgs = " "
        ffmpegCmd = (
            'ffmpeg -y -i "'
            + self.inputAudioFileSpec
            + '" '
            + audioArgs
            + f'{self.aParams} "'
            + self.outputAudioFileSpec
            + '"'
        )
        ffmpegResult = delegator.run(ffmpegCmd, block=True)
        if (ffmpegResult.return_code != 0) or (not os.path.isfile(self.outputAudioFileSpec)):
            print(ffmpegCmd)
            print(ffmpegResult.err)
            raise ValueError(f"Could not process {self.inputAudioFileSpec}")

        return self.outputAudioFileSpec


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
        type=str2bool,
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
        help="Input audio file (or URL)",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        type=str,
        default=None,
        required=False,
        metavar="<string>",
        help="Output audio file",
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
        help=f"Audio parameters for ffmpeg (default: \"{AUDIO_DEFAULT_PARAMS}\")",
        dest="aParams",
        default=AUDIO_DEFAULT_PARAMS,
    )
    parser.add_argument(
        "-x",
        "--extension",
        dest="outputExt",
        type=str,
        default=AUDIO_DEFAULT_EXTENSION,
        required=False,
        metavar="<string>",
        help=f"Output audio file extension (default: \"{AUDIO_DEFAULT_EXTENSION}\")",
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
        "-f",
        "--frames",
        dest="readFramesChunk",
        metavar="<int>",
        type=int,
        default=os.getenv("VOSK_READ_FRAMES", AUDIO_DEFAULT_WAV_FRAMES_CHUNK),
        help=f"WAV frame chunk (default: {AUDIO_DEFAULT_WAV_FRAMES_CHUNK})",
    )
    try:
        parser.error = parser.exit
        args = parser.parse_args()
    except SystemExit:
        parser.print_help()
        exit(2)

    if args.debug:
        eprint(os.path.join(script_path, script_name))
        eprint("Arguments: {}".format(sys.argv[1:]))
        eprint("Arguments: {}".format(args))
    else:
        sys.tracebacklimit = 0
        vosk.SetLogLevel(-1)

    if args.output:
        outFile = args.output
    elif args.input and os.path.isfile(args.input):
        outFile = os.path.splitext(args.input)[0] + "_clean." + args.outputExt
    elif args.input and args.input.lower().startswith("http"):
        outFile = os.path.splitext(os.path.basename(urlparse(args.input).path))[0] + "_clean." + args.outputExt
    else:
        outFile = "clean." + args.outputExt

    Plugger(
        args.input,
        outFile,
        args.swears,
        args.modelPath,
        args.aParams,
        args.readFramesChunk,
        args.debug,
    ).EncodeCleanAudio()


###################################################################################################
if __name__ == "__main__":
    RunMonkeyPlug()
