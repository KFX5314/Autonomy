# Private audio fixtures

Put local recordings here when you want to run the optional real-audio tests:

```powershell
cd backend
python -m pytest -m audio_real
```

Supported extensions are `.wav`, `.m4a`, `.mp3`, and `.aac`.

Do not commit real recordings. Voice and health context are sensitive data, and
this folder is ignored by Git except for this README.
