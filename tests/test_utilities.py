#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for the utilities module.

These tests validate the FFmpeg command construction, audio filter building,
and other utility functions extracted from the main monkeyplug module.
"""

import os
import tempfile
import pytest

import monkeyplug.utilities
from monkeyplug.utilities import (
    FFmpegCommandBuilder,
    AudioFilterBuilder,
    FFmpegRunner,
    get_codecs
)


def contains_in_nested(item, lst):
    """
    Check if item exists in list, recursively searching nested lists.
    
    This is needed because build_encode_command() creates nested list structures
    to match the main branch's behavior (audioArgs and audioParams are appended
    as nested lists, not extended).
    """
    for element in lst:
        if element == item:
            return True
        if isinstance(element, list) and contains_in_nested(item, element):
            return True
    return False


class TestFFmpegCommandBuilder:
    """Test FFmpeg command construction."""
    
    def test_build_encode_command_audio_only(self):
        """Test building FFmpeg encode command for audio-only output."""
        cmd = FFmpegCommandBuilder.build_encode_command(
            input_file="input.mp3",
            output_file="output.mp3",
            audio_params=["-c:a", "libmp3lame", "-b:a", "128K"],
            audio_args=None,
            video_mode=False
        )
        
        assert "ffmpeg" in cmd
        assert "-i" in cmd
        assert "input.mp3" in cmd
        assert "output.mp3" in cmd
        assert "-vn" in cmd
        assert "-sn" in cmd
        assert "-dn" in cmd
        # audio_params are nested, so use helper
        assert contains_in_nested("-c:a", cmd)
        assert contains_in_nested("libmp3lame", cmd)
        
        
    def test_build_intermediate_wav_command(self):
        """Test building FFmpeg WAV conversion command."""
        cmd = FFmpegCommandBuilder.build_intermediate_wav_command(
            input_file="input.mp3",
            output_file="output.wav",
            intermediate_params=["-c:a", "pcm_s16le", "-ac", "1", "-ar", "16000"]
        )
        
        assert "ffmpeg" in cmd
        assert "-i" in cmd
        assert "input.mp3" in cmd
        assert "output.wav" in cmd
        assert "-c:a" in cmd
        assert "pcm_s16le" in cmd
        assert "-ac" in cmd
        assert "1" in cmd
        assert "-ar" in cmd
        assert "16000" in cmd
        
    def test_build_probe_command(self):
        """Test building ffprobe command."""
        cmd = FFmpegCommandBuilder.build_probe_command("input.mp4")
        
        assert "ffprobe" in cmd
        assert "input.mp4" in cmd
        assert "-print_format" in cmd
        assert "json" in cmd
        assert "-show_format" in cmd
        assert "-show_streams" in cmd


class TestAudioFilterBuilder:
    """Test audio filter string construction."""
           
    def test_build_mute_filters_single(self):
        """Test building mute filters with single entry."""
        mute_list = ["volume=enable='between(t,1.0,2.0)':volume=0"]
        result = AudioFilterBuilder.build_mute_filters(mute_list)
        
        assert len(result) == 2
        assert result[0] == "-af"
        assert "volume=enable='between(t,1.0,2.0)':volume=0" in result[1]
        
    def test_build_mute_filters_multiple(self):
        """Test building mute filters with multiple entries."""
        mute_list = [
            "volume=enable='between(t,1.0,2.0)':volume=0",
            "volume=enable='between(t,3.0,4.0)':volume=0"
        ]
        result = AudioFilterBuilder.build_mute_filters(mute_list)
        
        assert len(result) == 2
        assert result[0] == "-af"
        assert "," in result[1]
        
    def test_build_beep_filters_single(self):
        """Test building beep filters with single entry."""
        mute_list = ["volume=enable='between(t,1.0,2.0)':volume=0"]
        sine_list = ["sine=f=1000:duration=1.0"]
        delay_list = ["atrim=0:1.0,adelay=1000|1000"]
        
        result = AudioFilterBuilder.build_beep_filters(
            mute_list, sine_list, delay_list,
            mix_normalize=False,
            audio_weight=1,
            sine_weight=1,
            dropout_transition=0
        )
        
        assert len(result) == 2
        assert result[0] == "-filter_complex"
        assert "amix" in result[1]
        assert "normalize=false" in result[1]
        
    def test_build_beep_filters_with_normalize(self):
        """Test beep filters with normalization enabled."""
        mute_list = ["volume=enable='between(t,1.0,2.0)':volume=0"]
        sine_list = ["sine=f=1000:duration=1.0"]
        delay_list = ["atrim=0:1.0,adelay=1000|1000"]
        
        result = AudioFilterBuilder.build_beep_filters(
            mute_list, sine_list, delay_list,
            mix_normalize=True,
            audio_weight=1,
            sine_weight=1,
            dropout_transition=0
        )
        
        assert "normalize=true" in result[1]
        
    def test_create_mute_time_entry(self):
        """Test creating mute time entry for a word."""
        entries = AudioFilterBuilder.create_mute_time_entry(
            start_time=1.5,
            end_time=2.0,
            peek_start_time=2.1
        )
        
        assert len(entries) == 2
        assert "afade" in entries[0]
        assert "afade" in entries[1]
        assert "1.500" in entries[0]
        assert "2.000" in entries[0]
        assert "2.100" in entries[1]
        
    def test_create_beep_entries(self):
        """Test creating beep entries for a word."""
        mute, sine, delay = AudioFilterBuilder.create_beep_entries(
            start_time=1.5,
            end_time=2.0,
            beep_hertz=1000
        )
        
        assert "volume=enable='between(t,1.500,2.000)':volume=0" == mute
        assert "sine=f=1000:duration=0.500" == sine
        assert "1500" in delay


class TestFFmpegRunner:
    """Test FFmpeg command execution (mocked)."""
    
    def test_run_command_mock(self, monkeypatch):
        """Test run_command calls mmguero.run_process."""
        called = []
        
        def mock_run_process(cmd, stdout=True, stderr=True, debug=False):
            called.append((cmd, stdout, stderr, debug))
            return (0, ["output"])
        
        monkeypatch.setattr(monkeyplug.utilities.mmguero, 'run_process', mock_run_process)
        
        result, output = FFmpegRunner.run_command(["ffmpeg", "-version"], debug=True)
        
        assert len(called) == 1
        assert called[0][0] == ["ffmpeg", "-version"]
        assert called[0][3] is True
        assert result == 0
        assert output == ["output"]


class TestGetCodecs:
    """Test codec detection function."""
        
    def test_get_codecs_structure(self, monkeypatch):
        """Test get_codecs returns expected structure."""
        def mock_run_probe(input_file, debug=False):
            return {
                'streams': [
                    {'codec_name': 'h264', 'codec_type': 'video'},
                    {'codec_name': 'aac', 'codec_type': 'audio'},
                    {'codec_name': 'subrip', 'codec_type': 'subtitle'}
                ],
                'format': {
                    'format_name': 'mp4,mov'
                }
            }
        
        monkeypatch.setattr(monkeyplug.utilities.FFmpegRunner, 'run_probe', mock_run_probe)
        
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            temp_file = tf.name
        
        try:
            result = get_codecs(temp_file, debug=False)
            
            assert 'video' in result
            assert 'audio' in result
            assert 'subtitle' in result
            assert 'format' in result
            
            assert 'h264' in result['video']
            assert 'aac' in result['audio']
            assert 'subrip' in result['subtitle']
            
            assert isinstance(result['format'], list)
            assert 'mp4' in result['format']
            assert 'mov' in result['format']
        finally:
            os.unlink(temp_file)
    
    def test_get_codecs_multiple_codecs_same_type(self, monkeypatch):
        """Test get_codecs handles multiple codecs of same type."""
        def mock_run_probe(input_file, debug=False):
            return {
                'streams': [
                    {'codec_name': 'h264', 'codec_type': 'video'},
                    {'codec_name': 'h265', 'codec_type': 'video'},
                    {'codec_name': 'aac', 'codec_type': 'audio'},
                    {'codec_name': 'ac3', 'codec_type': 'audio'}
                ],
                'format': {
                    'format_name': 'matroska'
                }
            }
        
        monkeypatch.setattr(monkeyplug.utilities.FFmpegRunner, 'run_probe', mock_run_probe)
        
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            temp_file = tf.name
        
        try:
            result = get_codecs(temp_file, debug=False)
            
            assert 'h264' in result['video']
            assert 'h265' in result['video']
            
            assert 'aac' in result['audio']
            assert 'ac3' in result['audio']
        finally:
            os.unlink(temp_file)

class TestUtilitiesIntegration:
    """Integration tests for utilities working together."""
    
    def test_encode_workflow(self):
        """Test typical encoding workflow using utilities."""
        audio_filters = AudioFilterBuilder.build_mute_filters([
            "volume=enable='between(t,1.0,2.0)':volume=0"
        ])
        
        cmd = FFmpegCommandBuilder.build_encode_command(
            input_file="input.mp3",
            output_file="output.mp3",
            audio_params=["-c:a", "libmp3lame", "-b:a", "128K"],
            audio_args=audio_filters,
            video_mode=False
        )
        
        assert "ffmpeg" in cmd
        # audio_args and audio_params are nested, so use helper
        assert contains_in_nested("-af", cmd)
        assert contains_in_nested("volume=enable='between(t,1.0,2.0)':volume=0", cmd)
        assert contains_in_nested("-c:a", cmd)
        assert contains_in_nested("libmp3lame", cmd)
        
    def test_beep_workflow(self):
        """Test beep encoding workflow."""
        mute_entry, sine_entry, delay_entry = AudioFilterBuilder.create_beep_entries(
            start_time=1.5,
            end_time=2.0,
            beep_hertz=1000
        )
        
        beep_filters = AudioFilterBuilder.build_beep_filters(
            mute_time_list=[mute_entry],
            sine_time_list=[sine_entry],
            beep_delay_list=[delay_entry],
            mix_normalize=True,
            audio_weight=1,
            sine_weight=1,
            dropout_transition=0
        )
        
        cmd = FFmpegCommandBuilder.build_encode_command(
            input_file="input.mp3",
            output_file="output.mp3",
            audio_params=["-c:a", "aac"],
            audio_args=beep_filters,
            video_mode=False
        )
        
        # audio_args are nested, so use helper
        assert contains_in_nested("-filter_complex", cmd)
        # Flatten the command before checking for "amix" since it's in a nested list
        def flatten(lst):
            for item in lst:
                if isinstance(item, list):
                    yield from flatten(item)
                else:
                    yield item
        flat_cmd = list(flatten(cmd))
        assert "amix" in ' '.join(flat_cmd)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
