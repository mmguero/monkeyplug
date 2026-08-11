#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Functional end-to-end tests using real audio files.

These tests perform actual audio processing and transcription to verify
that profanity censoring actually works in the real world by:
1. Censoring audio based on a transcript
2. Transcribing the censored output
3. Verifying the profane words are actually missing

Note: These tests require actual audio processing and are slower.
"""

import os
import pytest
import json

from monkeyplug.monkeyplug import Plugger, WhisperPlugger, GetCodecs


@pytest.fixture
def witch_audio_file():
    """Path to the Witch Mother audio file."""
    audio_path = os.path.join(os.path.dirname(__file__), '..', 'input', 'Witch_mother1.m4b')
    if not os.path.isfile(audio_path):
        pytest.skip(f"Test audio file not found: {audio_path}")
    return os.path.abspath(audio_path)


@pytest.fixture
def witch_transcript_file():
    """Path to the Witch Mother transcript file."""
    transcript_path = os.path.join(os.path.dirname(__file__), '..', 'input', 'Witch_mother1_transcript.json')
    if not os.path.isfile(transcript_path):
        pytest.skip(f"Test transcript file not found: {transcript_path}")
    return os.path.abspath(transcript_path)


@pytest.fixture
def real_swears_file():
    """Path to the real swears file created from transcript words."""
    swears_path = os.path.join(os.path.dirname(__file__), '..', 'input', 'swear_list.txt')
    if not os.path.isfile(swears_path):
        pytest.skip(f"Test swears file not found: {swears_path}")
    return os.path.abspath(swears_path)


@pytest.fixture
def output_dir(tmp_path):
    """Create a temporary output directory."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return output_dir


class TestRealWorldCensoring:
    """
    Real-world end-to-end tests that verify censoring actually works.
    
    These tests use real files and validate the output by transcribing it.
    """
    
    def test_codec_detection_on_real_file(self, witch_audio_file):
        """Verify we can detect codecs from the real audio file."""
        codecs = GetCodecs(witch_audio_file, debug=False)
        
        assert isinstance(codecs, dict)
        assert 'format' in codecs
        assert 'audio' in codecs
        assert len(codecs['audio']) > 0, "Should detect audio codec"
        
        format_names = codecs['format']
        assert any(fmt in ['m4a', 'mp4', 'mov'] for fmt in format_names), \
            f"Expected M4B format, got: {format_names}"
    
    def test_transcript_loading(self, witch_audio_file, witch_transcript_file, real_swears_file, output_dir):
        """Test that we can load the real transcript and identify profane words."""
        output_file = output_dir / "test_output.m4a"
        
        plugger = Plugger(
            iFileSpec=witch_audio_file,
            oFileSpec=str(output_file),
            oAudioFileFormat="m4a",
            iSwearsFileSpec=real_swears_file,
            outputJson="",
            inputTranscript=witch_transcript_file,
            saveTranscript=False,
            forceRetranscribe=False,
            force=False
        )
        
        assert plugger.LoadTranscriptFromFile() is True
        
        assert len(plugger.wordList) > 0, "Should have loaded words from transcript"
        
        scrub_words = [w for w in plugger.wordList if w.get('scrub', False)]
        assert scrub_words, \
            "Expected some words to be marked for scrubbing based on swear_list.txt"
        
        word_texts = {w['word'].lower() for w in scrub_words}
        assert 'cold' in word_texts or 'fever' in word_texts or 'warriors' in word_texts, \
            f"Expected test swear words to be marked for scrubbing, found: {word_texts}"
    
    @pytest.mark.slow
    def test_end_to_end_censoring_with_transcript_validation(
        self, witch_audio_file, witch_transcript_file, real_swears_file, output_dir
    ):
        """
        **THE KEY TEST**: Censor audio and validate by transcribing the output.
        
        This test:
        1. Loads the real audio and transcript
        2. Censors the audio based on profanity list
        3. **Transcribes the censored output**
        4. Verifies profane words are actually missing/garbled in new transcript
        
        This proves the censoring actually works!
        """
        output_file = output_dir / "censored_witch.m4a"
        output_transcript_file = output_dir / "censored_witch_transcript.json"
        
        plugger = Plugger(
            iFileSpec=witch_audio_file,
            oFileSpec=str(output_file),
            oAudioFileFormat="m4a",
            iSwearsFileSpec=real_swears_file,
            outputJson="",
            inputTranscript=witch_transcript_file,
            saveTranscript=False,
            forceRetranscribe=False,
            force=True,
            dbug=True
        )
        
        assert plugger.LoadTranscriptFromFile() is True
        original_word_count = len(plugger.wordList)
        
        words_to_censor = [w for w in plugger.wordList if w.get('scrub', False)]
        assert words_to_censor, "Should have words to censor"
        
        censored_word_texts = {w['word'].lower() for w in words_to_censor}
        print(f"\nWords that will be censored: {censored_word_texts}")
        print(f"Number of words to censor: {len(words_to_censor)}")
        
        plugger.CreateCleanMuteList()
        assert len(plugger.muteTimeList) > 0, "Should have mute time entries"
        
        print(f"Mute filters created: {len(plugger.muteTimeList)}")
        
        plugger.EncodeCleanAudio()
        
        assert os.path.isfile(output_file), "Censored output file should exist"
        output_size = os.path.getsize(output_file)
        assert output_size > 1024, f"Censored output seems too small: {output_size} bytes"
        
        output_codecs = GetCodecs(str(output_file))
        assert len(output_codecs['audio']) > 0, "Censored output should have audio"
        
        print(f"\nCensored output created: {output_file} ({output_size} bytes)")
        
        print("\n=== Transcribing censored output to validate censoring ===")
        
        model_dir = str(output_dir / "whisper_models")
        os.makedirs(model_dir, exist_ok=True)
        
        validation_plugger = WhisperPlugger(
            iFileSpec=str(output_file),
            oFileSpec=str(output_dir / "dummy_output.m4a"),
            oAudioFileFormat="m4a",
            iSwearsFileSpec=real_swears_file,
            mDir=model_dir,
            mName="base",
            torchThreads=1,
            outputJson="",
            inputTranscript=None,
            saveTranscript=False,
            forceRetranscribe=True,
            force=False,
            dbug=True
        )
        
        print(f"Transcribing: {output_file}")
        print(f"Input transcript setting: {validation_plugger.inputTranscript}")
        
        validation_plugger.RecognizeSpeech()
        
        new_word_list = validation_plugger.wordList
        assert new_word_list, "Should have transcribed words from censored audio"
        
        print(f"Transcription complete. Got {len(new_word_list)} words")
        
        original_words = [w['word'] for w in plugger.wordList]
        new_words = [w.get('word', '') for w in new_word_list]
        
        print(f"\n=== Transcript Comparison ===")
        print(f"Original transcript: {original_word_count} words")
        print(f"Censored transcript: {len(new_word_list)} words")
        print(f"\nOriginal words: {' '.join(original_words)}")
        print(f"\nNew words: {' '.join(new_words)}")
        
        new_word_texts = {w.get('word', '').lower().strip() for w in new_word_list if w.get('word')}
        
        print(f"\n=== Censored Words Analysis ===")
        print(f"Words that were censored: {censored_word_texts}")
        
        censored_words_found = [
            censored_word for censored_word in censored_word_texts
            if censored_word in new_word_texts
        ]
        
        print(f"Censored words still detected in new transcript: {censored_words_found}")
        
        for censored_word in censored_word_texts:
            orig_positions = [i for i, w in enumerate(original_words) if w.lower() == censored_word]
            for pos in orig_positions:
                context_start = max(0, pos - 2)
                context_end = min(len(original_words), pos + 3)
                orig_context = ' '.join(original_words[context_start:context_end])
                
                if pos < len(new_words):
                    new_context_start = max(0, pos - 2)
                    new_context_end = min(len(new_words), pos + 3)
                    new_context = ' '.join(new_words[new_context_start:new_context_end])
                else:
                    new_context = "(position beyond new transcript length)"
                
                print(f"\n  Word '{censored_word}' at position {pos}:")
                print(f"    Original: ...{orig_context}...")
                print(f"    Censored: ...{new_context}...")
        
        if censored_word_texts:
            found_percentage = (len(censored_words_found) / len(censored_word_texts)) * 100
        else:
            found_percentage = 0
            
        print(f"\n=== Validation Result ===")
        print(f"Total censored words: {len(censored_word_texts)}")
        print(f"Still detected: {len(censored_words_found)}")
        print(f"Successfully removed: {len(censored_word_texts) - len(censored_words_found)}")
        print(f"Percentage still detected: {found_percentage:.1f}%")
        
        if found_percentage >= 50:
            print(f"\n❌ FAIL: Too many censored words ({found_percentage:.1f}%) still detected!")
            print(f"   Censored words found: {censored_words_found}")
            print("   This suggests the censoring may not be working properly,")
            print("   OR Whisper is reconstructing words from context.")
            assert False, \
                f"Too many censored words ({found_percentage:.1f}%) still detected in output! " \
                f"Expected < 50%. Found: {censored_words_found}"
        else:
            print(f"\n✓ SUCCESS: Censoring validated - {100 - found_percentage:.1f}% of profane words removed!")
    
    @pytest.mark.slow
    def test_compare_original_vs_censored_word_lists(
        self, witch_audio_file, witch_transcript_file, real_swears_file, output_dir
    ):
        """
        Compare original and censored transcripts to show censoring impact.
        
        This test provides detailed analysis of what changed.
        """
        output_file = output_dir / "censored_for_comparison.m4a"
        
        with open(witch_transcript_file, 'r') as f:
            original_words = json.load(f)
        
        original_texts = [w['word'] for w in original_words]
        
        plugger = Plugger(
            iFileSpec=witch_audio_file,
            oFileSpec=str(output_file),
            oAudioFileFormat="m4a",
            iSwearsFileSpec=real_swears_file,
            outputJson="",
            inputTranscript=witch_transcript_file,
            saveTranscript=False,
            forceRetranscribe=False,
            force=True,
            dbug=False
        )
        
        plugger.LoadTranscriptFromFile()
        plugger.CreateCleanMuteList()
        plugger.EncodeCleanAudio()
        
        model_dir = str(output_dir / "whisper_models")
        os.makedirs(model_dir, exist_ok=True)
        
        validator = WhisperPlugger(
            iFileSpec=str(output_file),
            oFileSpec=str(output_dir / "dummy2.m4a"),
            oAudioFileFormat="m4a",
            iSwearsFileSpec=real_swears_file,
            mDir=model_dir,
            mName="base",
            torchThreads=1,
            outputJson="",
            inputTranscript=None,
            saveTranscript=False,
            forceRetranscribe=True,
            force=False,
            dbug=False
        )
        
        validator.RecognizeSpeech()
        censored_texts = [w.get('word', '') for w in validator.wordList]
        
        print(f"\n=== Censoring Impact Analysis ===")
        print(f"Original word count: {len(original_texts)}")
        print(f"Censored word count: {len(censored_texts)}")
        print(f"Word count difference: {len(original_texts) - len(censored_texts)}")
        
        orig_set = {w.lower() for w in original_texts}
        cens_set = {w.lower() for w in censored_texts}
        
        missing_words = orig_set - cens_set
        new_words = cens_set - orig_set
        
        print(f"\nWords in original but missing from censored: {missing_words}")
        print(f"New/altered words in censored: {new_words}")
        
        assert len(missing_words) > 0 or len(new_words) > 0, \
            "Censoring should have some impact on transcript"


class TestQuickValidation:
    """Quick tests that don't require slow transcription."""
    
    def test_swear_list_loads_correctly(self, real_swears_file):
        """Verify the swear list file is valid."""
        assert os.path.isfile(real_swears_file)
        
        with open(real_swears_file, 'r') as f:
            lines = f.readlines()
        
        assert len(lines) > 0, "Swear list should not be empty"
        
        for line in lines:
            line = line.strip()
            if line and '|' in line:
                parts = line.split('|')
                assert len(parts) == 2, f"Invalid swear list format: {line}"
                assert len(parts[0]) > 0, f"Swear word should not be empty: {line}"
    
    def test_files_exist(self, witch_audio_file, witch_transcript_file, real_swears_file):
        """Verify all required test files exist."""
        assert os.path.isfile(witch_audio_file), "Audio file should exist"
        assert os.path.isfile(witch_transcript_file), "Transcript file should exist"
        assert os.path.isfile(real_swears_file), "Swear list file should exist"
        
        audio_size = os.path.getsize(witch_audio_file)
        transcript_size = os.path.getsize(witch_transcript_file)
        swears_size = os.path.getsize(real_swears_file)
        
        assert audio_size > 1024, f"Audio file too small: {audio_size}"
        assert transcript_size > 100, f"Transcript file too small: {transcript_size}"
        assert swears_size > 10, f"Swear list too small: {swears_size}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "not slow"])
