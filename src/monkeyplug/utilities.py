#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FFmpeg command construction and audio processing utilities for monkeyplug.

This module provides utility classes for building and executing FFmpeg commands,
constructing audio filters, and analyzing media files. These utilities are extracted
from the main monkeyplug module to reduce code duplication and improve maintainability.
"""

import argparse
import importlib.metadata
import mmguero
import os


class FFmpegCommandBuilder:
    """Builds FFmpeg commands for audio encoding and processing."""
    
    @staticmethod
    def build_encode_command(input_file, output_file, audio_params, audio_args=None, video_mode=False):
        """
        Build FFmpeg command for encoding audio with optional filters.
        
        Args:
            input_file: Path to input file
            output_file: Path to output file
            audio_params: List of audio encoding parameters (e.g., ["-c:a", "aac", "-b:a", "128K"])
            audio_args: Optional audio filter arguments (e.g., ["-af", "volume=0"])
            video_mode: If True, copy video stream; if False, strip video
            
        Returns:
            List representing FFmpeg command
        """
        base = [
            'ffmpeg',
            '-nostdin',
            '-hide_banner',
            '-nostats',
            '-loglevel',
            'error',
            '-y',
            '-i',
            input_file,
        ]
        
        if video_mode:
            base.extend(['-c:v', 'copy', '-sn', '-dn'])
        else:
            base.extend(['-vn', '-sn', '-dn'])
        
        # Maintain compatibility with main branch: append lists as nested elements
        # Main branch builds: ffmpegCmd = ['ffmpeg', ..., audioArgs, self.aParams, output]
        if audio_args:
            base.append(audio_args)  
        
        base.append(audio_params)  
        base.append(output_file)
        
        return base
    
    @staticmethod
    def build_intermediate_wav_command(input_file, output_file, intermediate_params):
        """
        Build FFmpeg command to create intermediate WAV file.
        
        Args:
            input_file: Path to input file
            output_file: Path to output WAV file
            intermediate_params: WAV conversion parameters (e.g., ["-c:a", "pcm_s16le", "-ac", "1", "-ar", "16000"])
            
        Returns:
            List representing FFmpeg command
        """
        return ['ffmpeg', '-nostdin', '-hide_banner', '-nostats', '-loglevel', 'error', '-y',
                '-i', input_file, '-vn', '-sn', '-dn', *intermediate_params, output_file]
    
    @staticmethod
    def build_probe_command(input_file):
        """
        Build ffprobe command to get codec/format information.
        """
        return ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', input_file]


class AudioFilterBuilder:
    """Builds audio filter strings for muting/beeping profanity."""
    
    @staticmethod
    def build_mute_filters(mute_time_list):
        """
        Build FFmpeg audio filter arguments for muting.
        
        Args:
            mute_time_list: List of mute filter strings (e.g., ["volume=enable='between(t,1.0,2.0)':volume=0"])
        """
        return ['-af', ','.join(mute_time_list)] if mute_time_list else []
    
    @staticmethod
    def build_beep_filters(mute_time_list, sine_time_list, beep_delay_list, 
                          mix_normalize=False, audio_weight=1, sine_weight=1, dropout_transition=0):
        """
        Build FFmpeg audio filter arguments for beeping.
        
        Args:
            mute_time_list: List of mute filter strings
            sine_time_list: List of sine wave generation strings
            beep_delay_list: List of delay filter strings
            mix_normalize: Whether to normalize the audio mix
            audio_weight: Weight for original audio in mix
            sine_weight: Weight for beep tones in mix
            dropout_transition: Dropout transition time in seconds
            
        Returns:
            List of FFmpeg arguments (e.g., ["-filter_complex", "..."])
            Empty list if mute_time_list is empty
        """
        if not mute_time_list:
            return []
        
        mute_str = ','.join(mute_time_list)
        sine_str = ';'.join([f'{val}[beep{i+1}]' for i, val in enumerate(sine_time_list)])
        delay_str = ';'.join([f'[beep{i+1}]{val}[beep{i+1}_delayed]' for i, val in enumerate(beep_delay_list)])
        mix_list = ''.join([f'[beep{i+1}_delayed]' for i in range(len(beep_delay_list))])
        
        weights = f"{audio_weight} {' '.join([str(sine_weight)] * len(beep_delay_list))}"
        filter_str = (f"[0:a]{mute_str}[mute];{sine_str};{delay_str};"
                     f"[mute]{mix_list}amix=inputs={len(beep_delay_list)+1}:"
                     f"normalize={str(mix_normalize).lower()}:dropout_transition={dropout_transition}:weights={weights}")
        
        return ['-filter_complex', filter_str]
    
    @staticmethod
    def create_mute_time_entry(start_time, end_time, peek_start_time):
        """
        Create mute filter entries for a single word (fade out + fade in).
        
        Args:
            start_time: Start time of word in seconds
            end_time: End time of word in seconds
            peek_start_time: Time to start fading back in
            
        Returns:
            List of two filter strings (fade out, fade in)
        """
        start_str = format(start_time, ".3f")
        end_str = format(end_time, ".3f")
        peek_str = format(peek_start_time, ".3f")
        
        return [
            f"afade=enable='between(t,{start_str},{end_str})':t=out:st={start_str}:d=5ms",
            f"afade=enable='between(t,{end_str},{peek_str})':t=in:st={end_str}:d=5ms"
        ]
    
    @staticmethod
    def create_beep_entries(start_time, end_time, beep_hertz=1000):
        """
        Create beep filter entries for a single word.
        """
        start_str = format(start_time, ".3f")
        end_str = format(end_time, ".3f")
        duration = format(end_time - start_time, ".3f")
        delay_ms = int(start_time * 1000)
        
        mute_entry = f"volume=enable='between(t,{start_str},{end_str})':volume=0"
        sine_entry = f"sine=f={beep_hertz}:duration={duration}"
        delay_entry = f"atrim=0:{duration},adelay={'|'.join([str(delay_ms)] * 2)}"
        
        return (mute_entry, sine_entry, delay_entry)


class FFmpegRunner:
    """Executes FFmpeg commands and handles results."""
    
    @staticmethod
    def run_command(cmd, debug=False):
        """
        Execute an FFmpeg or ffprobe command.
        """
        return mmguero.run_process(cmd, stdout=True, stderr=True, debug=debug)
    
    @staticmethod
    def run_encode(input_file, output_file, audio_params, audio_args=None, video_mode=False, debug=False):
        """
        Execute FFmpeg encoding command and validate output.
        
        Args:
            input_file: Path to input file
            output_file: Path to output file
            audio_params: Audio encoding parameters
            audio_args: Optional audio filter arguments
            video_mode: If True, copy video stream
            debug: If True, print debug information
            
        Returns:
            Path to output file
            
        Raises:
            ValueError: If encoding fails or output file not created
        """
        base = FFmpegCommandBuilder.build_encode_command(input_file, output_file, audio_params, audio_args, video_mode)
        result, output = FFmpegRunner.run_command(base, debug=debug)
        
        if result != 0 or not os.path.isfile(output_file):
            mmguero.eprint(' '.join(mmguero.flatten(base)))
            mmguero.eprint(result)
            mmguero.eprint(output)
            raise ValueError(f"Could not process {input_file}")
        
        return output_file
    
    @staticmethod
    def run_probe(input_file, debug=False):
        """
        Execute ffprobe and return parsed JSON result.
        """
        base = FFmpegCommandBuilder.build_probe_command(input_file)
        # Note: ffprobe uses stderr=False to match main branch behavior
        result, output = mmguero.run_process(base, stdout=True, stderr=False, debug=debug)
        
        if result != 0:
            mmguero.eprint(' '.join(mmguero.flatten(base)))
            mmguero.eprint(result)
            mmguero.eprint(output)
            raise ValueError(f"Could not analyze {input_file}")
        
        return mmguero.load_str_if_json(' '.join(output))


def get_codecs(local_filename, debug=False):
    """
    Get stream codecs from an input filename.
    
    Args:
        local_filename: Path to media file
        debug: If True, print debug information
        
    Returns:
        Dict with codec information:
        {
            'video': {'h264'},
            'audio': {'eac3'}, 
            'subtitle': {'subrip'},
            'format': ['mp4', 'mov']
        }
    """
    result = {}
    
    if not os.path.isfile(local_filename):
        return result
    
    probe_output = FFmpegRunner.run_probe(local_filename, debug=debug)
    
    if 'streams' in probe_output:
        for stream in probe_output['streams']:
            if 'codec_name' in stream and 'codec_type' in stream:
                codec_type = stream['codec_type'].lower()
                codec_value = stream['codec_name'].lower()
                
                if codec_type in result:
                    result[codec_type].add(codec_value)
                else:
                    result[codec_type] = {codec_value}
    
    result['format'] = mmguero.deep_get(probe_output, ['format', 'format_name'])
    if isinstance(result['format'], str):
        result['format'] = result['format'].split(',')
    
    return result


def create_argument_parser(script_path, package_name="monkeyplug", constants=None):
    """
    Create and configure the ArgumentParser for monkeyplug CLI.
    
    Args:
        script_path: Path to the script directory (used for default swears file)
        package_name: Name of the package (default: "monkeyplug")
        constants: Dictionary of constants for defaults. If None, uses built-in defaults.
        
    Returns:
        Configured ArgumentParser instance
    """
    if constants is None:
        constants = {}
    
    try:
        metadata = importlib.metadata.metadata(package_name)
        version = metadata.get("Version", "unknown")
    except importlib.metadata.PackageNotFoundError:
        version = "source"
    
    SPEECH_REC_MODE_VOSK = constants.get('SPEECH_REC_MODE_VOSK', "vosk")
    SPEECH_REC_MODE_WHISPER = constants.get('SPEECH_REC_MODE_WHISPER', "whisper")
    DEFAULT_SPEECH_REC_MODE = constants.get('DEFAULT_SPEECH_REC_MODE', SPEECH_REC_MODE_WHISPER)
    DEFAULT_VOSK_MODEL_DIR = constants.get('DEFAULT_VOSK_MODEL_DIR', os.path.expanduser("~/.local/share/vosk"))
    DEFAULT_WHISPER_MODEL_DIR = constants.get('DEFAULT_WHISPER_MODEL_DIR', os.path.expanduser("~/.cache/whisper"))
    DEFAULT_WHISPER_MODEL_NAME = constants.get('DEFAULT_WHISPER_MODEL_NAME', "small.en")
    DEFAULT_TORCH_THREADS = constants.get('DEFAULT_TORCH_THREADS', 0)
    SWEARS_FILENAME_DEFAULT = constants.get('SWEARS_FILENAME_DEFAULT', 'swears.txt')
    AUDIO_DEFAULT_CHANNELS = constants.get('AUDIO_DEFAULT_CHANNELS', 2)
    AUDIO_DEFAULT_SAMPLE_RATE = constants.get('AUDIO_DEFAULT_SAMPLE_RATE', 48000)
    AUDIO_DEFAULT_BIT_RATE = constants.get('AUDIO_DEFAULT_BIT_RATE', "256K")
    AUDIO_DEFAULT_VORBIS_QSCALE = constants.get('AUDIO_DEFAULT_VORBIS_QSCALE', 5)
    AUDIO_MATCH_FORMAT = constants.get('AUDIO_MATCH_FORMAT', "MATCH")
    AUDIO_DEFAULT_WAV_FRAMES_CHUNK = constants.get('AUDIO_DEFAULT_WAV_FRAMES_CHUNK', 8000)
    BEEP_HERTZ_DEFAULT = constants.get('BEEP_HERTZ_DEFAULT', 1000)
    BEEP_MIX_NORMALIZE_DEFAULT = constants.get('BEEP_MIX_NORMALIZE_DEFAULT', False)
    BEEP_AUDIO_WEIGHT_DEFAULT = constants.get('BEEP_AUDIO_WEIGHT_DEFAULT', 1)
    BEEP_SINE_WEIGHT_DEFAULT = constants.get('BEEP_SINE_WEIGHT_DEFAULT', 1)
    BEEP_DROPOUT_TRANSITION_DEFAULT = constants.get('BEEP_DROPOUT_TRANSITION_DEFAULT', 0)

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
    whisperArgGroup.add_argument(
        "--torch-threads",
        dest="torchThreads",
        metavar="<int>",
        type=int,
        default=DEFAULT_TORCH_THREADS,
        help=f"Number of threads used by torch for CPU inference ({DEFAULT_TORCH_THREADS})",
    )

    return parser
