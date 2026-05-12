import os
from pathlib import Path

import pytest


pytestmark = pytest.mark.audio_real


def test_real_audio_fixtures_can_be_transcribed():
    fixtures_dir = os.getenv("TFG_AUDIO_FIXTURES_DIR")
    if not fixtures_dir:
        pytest.skip("Set TFG_AUDIO_FIXTURES_DIR to run local real-audio validation.")

    audio_dir = Path(fixtures_dir)
    if not audio_dir.exists():
        pytest.skip(f"Audio fixtures directory does not exist: {audio_dir}")

    audio_files = [
        path
        for path in audio_dir.iterdir()
        if path.suffix.lower() in {".wav", ".m4a", ".mp3", ".aac"}
    ]
    if not audio_files:
        pytest.skip(f"No supported audio files found in {audio_dir}")

    from src.services.stt_service import transcribe_audio

    for audio_path in audio_files:
        result = transcribe_audio(str(audio_path))

        assert "text" in result
        assert "language" in result
        assert "segments" in result
