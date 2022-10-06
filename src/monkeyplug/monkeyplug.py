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
AUDIO_DEFAULT_PARAMS = {
    "flac": "-c:a flac -ar 44100 -ac 2",
    "m4a": "-c:a aac -ab 128k -ar 44100 -ac 2",
    "mp3": "-c:a libmp3lame -ab 128k -ar 44100 -ac 2",
    "ogg": "-c:a libvorbis -qscale:a 4 -ar 44100 -ac 2",
    "opus": "-c:a libopus -b:a 128K -ar 48000 -ac 2",
}
AUDIO_DEFAULT_EXTENSION = "mp3"
AUDIO_MATCH_EXTENSION = "MATCH"
AUDIO_INTERMEDIATE_PARAMS = "-c:a pcm_s16le -ac 1 -ar 16000"
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


#################################################################################
class Plugger(object):
    debug = False
    inputAudioFileSpec = ""
    outputAudioFileSpec = ""
    outputAudioFileExt = ""
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
        iAudioFileSpec,
        oAudioFileSpec,
        oAudioFileExt,
        iSwearsFileSpec,
        mPath,
        aParams=None,
        wChunk=AUDIO_DEFAULT_WAV_FRAMES_CHUNK,
        force=False,
        dbug=False,
    ):
        self.wavReadFramesChunk = wChunk
        self.forceDespiteTag = force
        self.debug = dbug

        # make sure the VOSK model path exists
        if (mPath is not None) and os.path.isdir(mPath):
            self.modelPath = mPath
        else:
            raise IOError(
                errno.ENOENT,
                os.strerror(errno.ENOENT) + " (see https://alphacephei.com/vosk/models)",
                mPath,
            )

        # determine input audio file name, or download and save audio file
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

        # input file should exist locally by now
        if os.path.isfile(self.inputAudioFileSpec):
            inParts = os.path.splitext(self.inputAudioFileSpec)
        else:
            raise IOError(errno.ENOENT, os.strerror(errno.ENOENT), self.inputAudioFileSpec)

        # determine output audio file name (either specified or based on input filename)
        if (oAudioFileSpec is not None) and (len(oAudioFileSpec) > 0):
            # output filename was specified
            self.outputAudioFileSpec = oAudioFileSpec
        else:
            if (oAudioFileExt is not None) and (oAudioFileExt.upper() == AUDIO_MATCH_EXTENSION):
                # output filename not specified, base on input filename matching extension
                self.outputAudioFileSpec = inParts[0] + "_clean" + inParts[1]
            elif (oAudioFileExt is not None) and (len(oAudioFileExt) > 0):
                # output filename not specified, base on input filename with specified extension
                self.outputAudioFileSpec = inParts[0] + "_clean." + oAudioFileExt.lower().lstrip('.')
            else:
                # can't determine what output audio file extension should be
                raise ValueError("Output audio file extension unspecified")

        # determine output audio file extension if it's not already obvious
        outParts = os.path.splitext(self.outputAudioFileSpec)
        self.outputAudioFileExt = outParts[1].lower().lstrip('.')

        if len(self.outputAudioFileExt) == 0:
            # we don't know the output extension yet (not specified as part of output audio file)
            if (oAudioFileExt is not None) and (oAudioFileExt.upper() == AUDIO_MATCH_EXTENSION):
                self.outputAudioFileSpec = self.outputAudioFileSpec + inParts[1]
            elif (oAudioFileExt is not None) and (len(oAudioFileExt) > 0):
                self.outputAudioFileSpec = self.outputAudioFileSpec + '.' + oAudioFileExt.lower().lstrip('.')
            else:
                raise ValueError("Output audio file extension unspecified")
            outParts = os.path.splitext(self.outputAudioFileSpec)
            self.outputAudioFileExt = outParts[1].lower().lstrip('.')

        if (len(self.outputAudioFileExt) == 0) or (
            ((aParams is None) or (len(aParams) == 0)) and (self.outputAudioFileExt not in AUDIO_DEFAULT_PARAMS)
        ):
            raise ValueError("Output audio file extension unspecified or unsupported")

        # if output file already exists, remove as we'll be overwriting it anyway
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

        if (aParams is None) or (len(aParams) == 0):
            # we're using ffmpeg encoding params based on output audio file extension
            self.aParams = AUDIO_DEFAULT_PARAMS[self.outputAudioFileExt]
        else:
            # they specified custom ffmpeg encoding params
            self.aParams = aParams
            if self.aParams.startswith("base64:"):
                self.aParams = base64.b64decode(self.aParams[7:]).decode("utf-8")

        if self.debug:
            mmguero.eprint(f'Input: {self.inputAudioFileSpec}')
            mmguero.eprint(f'Output: {self.outputAudioFileSpec}')
            mmguero.eprint(f'Output Extension: {self.outputAudioFileExt}')
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
            mmguero.eprint(ffmpegCmd)
            mmguero.eprint(ffmpegResult.err)
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
                mmguero.eprint(json.dumps(self.wordList))

        return self.wordList

    ######## CreateCleanMuteList #################################################
    def CreateCleanMuteList(self):
        self.CreateIntermediateWAV()
        self.RecognizeSpeech()

        self.naughtyWordList = [word for word in self.wordList if (word["word"].lower() in self.swearsMap)]
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
        if (self.forceDespiteTag is True) or (GetMonkeyplugTagged(self.inputAudioFileSpec, debug=self.debug) is False):
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
                mmguero.eprint(ffmpegCmd)
                mmguero.eprint(ffmpegResult.err)
                raise ValueError(f"Could not process {self.inputAudioFileSpec}")

            SetMonkeyplugTag(self.outputAudioFileSpec, debug=self.debug)
            return self.outputAudioFileSpec

        else:
            return self.inputAudioFileSpec


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
        help=f"Audio parameters for ffmpeg (default depends on output audio file type\")",
        dest="aParams",
        default=None,
    )
    parser.add_argument(
        "-x",
        "--extension",
        dest="outputExt",
        type=str,
        default=AUDIO_MATCH_EXTENSION,
        required=False,
        metavar="<string>",
        help=f"Output audio file extension (default: extension of --output, or \"{AUDIO_MATCH_EXTENSION}\")",
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
            args.outputExt,
            args.swears,
            args.modelPath,
            aParams=args.aParams,
            wChunk=args.readFramesChunk,
            force=args.forceDespiteTag,
            dbug=args.debug,
        ).EncodeCleanAudio()
    )


###################################################################################################
if __name__ == "__main__":
    RunMonkeyPlug()
