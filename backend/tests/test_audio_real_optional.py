import os
from pathlib import Path

import pytest


pytestmark = pytest.mark.audio_real
DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "private_audio"


def test_real_audio_fixtures_can_be_transcribed():
    fixtures_dir = os.getenv("TFG_AUDIO_FIXTURES_DIR")
    audio_dir = Path(fixtures_dir) if fixtures_dir else DEFAULT_FIXTURES_DIR
    if not audio_dir.exists():
        pytest.skip(f"Audio fixtures directory does not exist: {audio_dir}. Create it or set TFG_AUDIO_FIXTURES_DIR.")

    audio_files = [
        path
        for path in audio_dir.iterdir()
        if path.suffix.lower() in {".wav", ".m4a", ".mp3", ".aac"}
    ]
    if not audio_files:
        pytest.skip(
            f"No supported audio files found in {audio_dir}. "
            "Record a private .wav, .m4a, .mp3, or .aac file and place it there."
        )

    from src.services.stt_service import transcribe_audio

    for audio_path in audio_files:
        result = transcribe_audio(str(audio_path))

        assert "text" in result
        assert "language" in result
        assert "segments" in result
