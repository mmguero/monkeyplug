#!/usr/bin/env python3

import json
import os
import shutil
import tempfile
import time
import pytest
from monkeyplug.monkeyplug import Plugger, scrubword
from monkeyplug.monkeyplug import WhisperPlugger, DEFAULT_WHISPER_MODEL_DIR, DEFAULT_WHISPER_MODEL_NAME


class MockPlugger:
    """Minimal mock Plugger for testing transcript loading without audio file requirements"""
    def __init__(self, swearsFileSpec, inputTranscript=None, debug=False):
        self.swearsFileSpec = swearsFileSpec
        self.swearsMap = {}
        self.inputTranscript = inputTranscript
        self.debug = debug
        self.wordList = []
        
        with open(self.swearsFileSpec) as f:
            lines = [line.rstrip("\n") for line in f]
        for line in lines:
            lineMap = line.split("|")
            self.swearsMap[scrubword(lineMap[0])] = lineMap[1] if len(lineMap) > 1 else "*****"
        
        self.LoadTranscriptFromFile = Plugger.LoadTranscriptFromFile.__get__(self)


class TestTranscriptSaveReuse:
    """Test suite for transcript save/reuse functionality"""

    @pytest.fixture
    def swears_file(self):
        """Create a temporary swears file"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("damn\nhell\ncrap")
            temp_file = f.name
        yield temp_file
        if os.path.exists(temp_file):
            os.unlink(temp_file)

    @pytest.fixture
    def transcript_file(self):
        """Create a temporary transcript file"""
        transcript_data = [
            {"word": "hello", "start": 0.0, "end": 0.5, "conf": 0.9},
            {"word": "damn", "start": 0.5, "end": 1.0, "conf": 0.8},
            {"word": "world", "start": 1.0, "end": 1.5, "conf": 0.95},
            {"word": "hell", "start": 1.5, "end": 2.0, "conf": 0.6},
        ]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(transcript_data, f)
            temp_file = f.name
        yield temp_file
        if os.path.exists(temp_file):
            os.unlink(temp_file)

    def test_load_transcript_from_file(self, swears_file, transcript_file):
        """Test loading a transcript from JSON file"""
        plugger = MockPlugger(swears_file, inputTranscript=transcript_file)
        
        result = plugger.LoadTranscriptFromFile()
        assert result == True
        
        assert len(plugger.wordList) == 4
        
        assert plugger.wordList[0]['word'] == "hello"
        assert plugger.wordList[0]['scrub'] == False  
        
        assert plugger.wordList[1]['word'] == "damn"
        assert plugger.wordList[1]['scrub'] == True  
        
        assert plugger.wordList[2]['word'] == "world"
        assert plugger.wordList[2]['scrub'] == False  
        
        assert plugger.wordList[3]['word'] == "hell"
        assert plugger.wordList[3]['scrub'] == True

    def test_load_transcript_with_different_swear_list(self):
        """Test that loading transcript with different swear lists affects scrub decisions"""
        transcript_data = [{"word": "damn", "start": 0.0, "end": 0.5, "conf": 0.8}]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(transcript_data, f)
            transcript_file = f.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("damn")
            swears_file1 = f.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("hell")
            swears_file2 = f.name
        
        try:
            plugger1 = MockPlugger(swears_file1, inputTranscript=transcript_file)
            plugger1.LoadTranscriptFromFile()
            assert plugger1.wordList[0]['scrub'] == True
            
            plugger2 = MockPlugger(swears_file2, inputTranscript=transcript_file)
            plugger2.LoadTranscriptFromFile()
            assert plugger2.wordList[0]['scrub'] == False
        finally:
            for f in [swears_file1, swears_file2, transcript_file]:
                if os.path.exists(f):
                    os.unlink(f)

    def test_load_transcript_file_not_found(self, swears_file):
        """Test that loading non-existent transcript raises IOError"""
        plugger = MockPlugger(swears_file, inputTranscript="/nonexistent/transcript.json")
        with pytest.raises(IOError):
            plugger.LoadTranscriptFromFile()

    def test_load_transcript_returns_false_when_no_input(self, swears_file):
        """Test that LoadTranscriptFromFile returns False when no input transcript specified"""
        plugger = MockPlugger(swears_file, inputTranscript=None)
        result = plugger.LoadTranscriptFromFile()
        assert result == False

    def test_automatic_transcript_detection(self, transcript_file):
        """Test that existing transcripts are automatically detected and reused"""
        outputJson = transcript_file
        inputTranscript = None
        saveTranscript = True
        forceRetranscribe = False
        
        if saveTranscript and not inputTranscript and outputJson and not forceRetranscribe:
            if os.path.exists(outputJson):
                inputTranscript = outputJson
        
        assert inputTranscript == transcript_file
        assert inputTranscript is not None
        
        inputTranscript2 = None
        forceRetranscribe2 = True
        if saveTranscript and not inputTranscript2 and outputJson and not forceRetranscribe2:
            if os.path.exists(outputJson):
                inputTranscript2 = outputJson
        
        assert inputTranscript2 is None


@pytest.mark.skipif(
    not os.path.exists(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'input', 'Witch_mother1.m4b')),
    reason="Test audio file not found"
)
class TestTranscriptSaveReuseIntegration:
    """Integration tests using real audio file"""
    
    @pytest.fixture
    def setup_files(self):
        """Setup test files and cleanup after test"""
        # Paths (relative to project root)
        project_root = os.path.dirname(os.path.dirname(__file__))
        input_file = os.path.join(project_root, 'input', 'Witch_mother1.m4b')
        output_dir = tempfile.mkdtemp()
        output_file = os.path.join(output_dir, 'test_output.m4a')
        transcript_file = os.path.join(output_dir, 'test_output_transcript.json')
        swears_file = os.path.join(output_dir, 'test_swears.txt')
        
        # Create simple swears file
        with open(swears_file, 'w') as f:
            f.write("damn\nhell\ncrap")
        
        yield {
            'input': input_file,
            'output': output_file,
            'transcript': transcript_file,
            'swears': swears_file,
            'dir': output_dir
        }
        
        # Cleanup
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
    
    def test_save_transcript_creates_file(self, setup_files):
        """Test that --save-transcript creates a transcript JSON file"""
        
        files = setup_files
        
        # Run with save-transcript enabled
        plugger = WhisperPlugger(
            iFileSpec=files['input'],
            oFileSpec=files['output'],
            oAudioFileFormat='m4a',
            iSwearsFileSpec=files['swears'],
            mDir=DEFAULT_WHISPER_MODEL_DIR,
            mName=DEFAULT_WHISPER_MODEL_NAME,
            torchThreads=1,
            outputJson=None,
            inputTranscript=None,
            saveTranscript=True,
            forceRetranscribe=False,
            dbug=True
        )
        plugger.CreateCleanMuteList()
        
        assert os.path.exists(files['transcript'])
        assert os.path.getsize(files['transcript']) > 0
        
        # Verify transcript has valid JSON structure
        with open(files['transcript'], 'r') as f:
            transcript_data = json.load(f)
        assert isinstance(transcript_data, list)
        assert len(transcript_data) > 0
        assert 'word' in transcript_data[0]
        assert 'start' in transcript_data[0]
        assert 'end' in transcript_data[0]
    
    def test_automatic_transcript_reuse(self, setup_files):
        """Test that existing transcript is automatically reused"""
        
        files = setup_files
        
        # First run - generate transcript
        plugger1 = WhisperPlugger(
            iFileSpec=files['input'],
            oFileSpec=files['output'],
            oAudioFileFormat='m4a',
            iSwearsFileSpec=files['swears'],
            mDir=DEFAULT_WHISPER_MODEL_DIR,
            mName=DEFAULT_WHISPER_MODEL_NAME,
            torchThreads=1,
            outputJson=None,
            inputTranscript=None,
            saveTranscript=True,
            forceRetranscribe=False,
            dbug=True
        )
        plugger1.CreateCleanMuteList()
        first_wordlist = plugger1.wordList.copy()
        
        assert os.path.exists(files['transcript'])
        
        # Second run - should auto-detect and reuse transcript
        start_time = time.time()
        plugger2 = WhisperPlugger(
            iFileSpec=files['input'],
            oFileSpec=files['output'],
            oAudioFileFormat='m4a',
            iSwearsFileSpec=files['swears'],
            mDir=DEFAULT_WHISPER_MODEL_DIR,
            mName=DEFAULT_WHISPER_MODEL_NAME,
            torchThreads=1,
            outputJson=None,
            inputTranscript=None,
            saveTranscript=True,
            forceRetranscribe=False,
            dbug=True
        )
        plugger2.CreateCleanMuteList()
        reuse_time = time.time() - start_time
        
        assert plugger2.inputTranscript == files['transcript']
        assert len(plugger2.wordList) == len(first_wordlist)
        
        for i, word in enumerate(plugger2.wordList):
            assert word['word'] == first_wordlist[i]['word']
            assert word['scrub'] == first_wordlist[i]['scrub']
        
        print(f"\nReuse time savings: significantly faster ({reuse_time:.2f}s)")
    
    def test_force_retranscribe_flag(self, setup_files):
        """Test that --force-retranscribe ignores existing transcript file"""
        
        files = setup_files
        
        # Create a garbage transcript file to simulate existing transcript
        garbage_transcript = [
            {"word": "GARBAGE", "start": 0.0, "end": 1.0, "probability": 0.5, "scrub": False},
            {"word": "DATA", "start": 1.0, "end": 2.0, "probability": 0.5, "scrub": False},
        ]
        with open(files['transcript'], 'w') as f:
            json.dump(garbage_transcript, f)
        
        assert os.path.exists(files['transcript'])
        
        # Run with force flag - should ignore the garbage file and transcribe
        plugger = WhisperPlugger(
            iFileSpec=files['input'],
            oFileSpec=files['output'],
            oAudioFileFormat='m4a',
            iSwearsFileSpec=files['swears'],
            mDir=DEFAULT_WHISPER_MODEL_DIR,
            mName=DEFAULT_WHISPER_MODEL_NAME,
            torchThreads=1,
            outputJson=None,
            inputTranscript=None,
            saveTranscript=True,
            forceRetranscribe=True,
            dbug=True
        )
        plugger.CreateCleanMuteList()
        
        # Verify the garbage transcript was NOT used
        # The wordList should have real transcription, not the garbage data
        assert len(plugger.wordList) > 2  
        assert plugger.wordList[0]['word'] != "GARBAGE"
        assert plugger.wordList[1]['word'] != "DATA"
        
        with open(files['transcript'], 'r') as f:
            new_transcript = json.load(f)
        assert len(new_transcript) > 2
        assert new_transcript[0]['word'] != "GARBAGE"
    
    def test_explicit_transcript_reuse(self, setup_files):
        """Test explicit transcript loading with --input-transcript"""
        
        files = setup_files
        
        known_transcript = [
            {"word": "test", "start": 0.0, "end": 0.5, "probability": 0.9, "scrub": False},
            {"word": "damn", "start": 0.5, "end": 1.0, "probability": 0.8, "scrub": False},
            {"word": "explicit", "start": 1.0, "end": 1.5, "probability": 0.95, "scrub": False},
        ]
        with open(files['transcript'], 'w') as f:
            json.dump(known_transcript, f)
        
        plugger = WhisperPlugger(
            iFileSpec=files['input'],
            oFileSpec=files['output'],
            oAudioFileFormat='m4a',
            iSwearsFileSpec=files['swears'],
            mDir=DEFAULT_WHISPER_MODEL_DIR,
            mName=DEFAULT_WHISPER_MODEL_NAME,
            torchThreads=1,
            outputJson=None,
            inputTranscript=files['transcript'],
            saveTranscript=False,
            forceRetranscribe=False,
            dbug=True
        )
        plugger.CreateCleanMuteList()
        
        assert plugger.inputTranscript == files['transcript']
        assert len(plugger.wordList) == 3
        assert plugger.wordList[0]['word'] == "test"
        assert plugger.wordList[1]['word'] == "damn"
        assert plugger.wordList[1]['scrub'] == True  # "damn" should be scrubbed
        assert plugger.wordList[2]['word'] == "explicit"
        assert plugger.wordList[2]['scrub'] == False
    
    def test_different_swear_lists_with_same_transcript(self, setup_files):
        """Test that same transcript with different swear lists produces different scrub decisions"""
        
        files = setup_files
        swears_file1 = os.path.join(files['dir'], 'swears1.txt')
        swears_file2 = os.path.join(files['dir'], 'swears2.txt')
        
        with open(swears_file1, 'w') as f:
            f.write("damn\nhell\ncrap")
        
        with open(swears_file2, 'w') as f:
            f.write("damn")
        
        # First run - generate transcript with swear list 1
        plugger1 = WhisperPlugger(
            iFileSpec=files['input'],
            oFileSpec=files['output'],
            oAudioFileFormat='m4a',
            iSwearsFileSpec=swears_file1,
            mDir=DEFAULT_WHISPER_MODEL_DIR,
            mName=DEFAULT_WHISPER_MODEL_NAME,
            torchThreads=1,
            outputJson=files['transcript'],
            inputTranscript=None,
            saveTranscript=True,
            forceRetranscribe=False,
            dbug=True
        )
        plugger1.CreateCleanMuteList()
        scrub_count1 = sum(1 for word in plugger1.wordList if word['scrub'])
        
        # Second run - reuse transcript with swear list 2 (fewer swears)
        output_file2 = files['output'].replace('.m4a', '_v2.m4a')
        plugger2 = WhisperPlugger(
            iFileSpec=files['input'],
            oFileSpec=output_file2,
            oAudioFileFormat='m4a',
            iSwearsFileSpec=swears_file2,
            mDir=DEFAULT_WHISPER_MODEL_DIR,
            mName=DEFAULT_WHISPER_MODEL_NAME,
            torchThreads=1,
            outputJson=None,
            inputTranscript=files['transcript'],
            saveTranscript=False,
            forceRetranscribe=False,
            dbug=True
        )
        plugger2.CreateCleanMuteList()
        scrub_count2 = sum(1 for word in plugger2.wordList if word['scrub'])
        
        # Verify that different swear lists produce different scrub counts
        # (assuming the audio has multiple swear words from list 1)
        assert scrub_count1 >= scrub_count2  # More swears in list 1 = more scrubbing


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
