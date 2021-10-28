#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import sys
import wave

from vosk import Model, KaldiRecognizer, SetLogLevel
from mmguero import eprint
import mmguero

###################################################################################################
args = None
debug = False
script_name = os.path.basename(__file__)
script_path = os.path.dirname(os.path.realpath(__file__))
orig_path = os.getcwd()

###################################################################################################
# main
def main():
  global args
  global debug

  parser = argparse.ArgumentParser(description=script_name, add_help=False, usage='{} <arguments>'.format(script_name))
  parser.add_argument('-v', '--verbose', dest='debug', type=mmguero.str2bool, nargs='?', const=True, default=False, metavar='true|false', help="Verbose/debug output")
  parser.add_argument('-i', '--input', dest='input', type=str, default=None, required=False, metavar='<string>', help="Input audio file")
  parser.add_argument('-m', '--model', dest='modelPath', metavar='<string>', type=str, default=os.getenv('VOSK_MODEL', os.path.join(script_path, 'model')), help='Vosk model path')
  try:
    parser.error = parser.exit
    args = parser.parse_args()
  except SystemExit:
    parser.print_help()
    exit(2)

  debug = args.debug
  if debug:
    eprint(os.path.join(script_path, script_name))
    eprint("Arguments: {}".format(sys.argv[1:]))
    eprint("Arguments: {}".format(args))
  else:
    sys.tracebacklimit = 0

  if (args.input is None) or (not os.path.isfile(args.input)):
    raise Exception(f'Input audio file ({args.input}) not specified or does not exist')

  if (args.modelPath is None) or (not os.path.isdir(args.modelPath)):
    raise Exception(f'Vosk model path ({args.modelPath}) not specified or does not exist (see https://alphacephei.com/vosk/models)')


  with wave.open(args.input, "rb") as wf:
    if (wf.getnchannels() != 1) or (wf.getframerate() != 16000) or (wf.getsampwidth() != 2) or (wf.getcomptype() != "NONE"):
      raise Exception(f'Audio file ({args.modelPath}) must be 16000 Hz, mono, s16 PCM WAV')

    words = []
    SetLogLevel(-1)
    rec = KaldiRecognizer(Model(args.modelPath), wf.getframerate())
    rec.SetWords(True)
    while True:
      data = wf.readframes(16000)
      if len(data) == 0:
        break
      if rec.AcceptWaveform(data):
        res = json.loads(rec.Result())
        if 'result' in res:
          words.extend(res['result'])

    res = json.loads(rec.FinalResult())
    if 'result' in res:
      words.extend(res['result'])

    if debug:
      eprint(json.dumps(words))
    else:
      eprint(' '.join([x['word'] for x in words]))

###################################################################################################
if __name__ == '__main__':
  main()
