/**
 * Frontend runtime configuration.
 *
 * Expo exposes variables prefixed with EXPO_PUBLIC_ through process.env.
 * Keep operational timings and thresholds here so tuning does not require
 * hunting through screen components.
 */

const publicEnv = {
  serverUrl: process.env.EXPO_PUBLIC_SERVER_URL,
  audioChunkTimeoutMs: process.env.EXPO_PUBLIC_AUDIO_CHUNK_TIMEOUT_MS,
  audioChunkMaxRetries: process.env.EXPO_PUBLIC_AUDIO_CHUNK_MAX_RETRIES,
  audioChunkRetryDelayMs: process.env.EXPO_PUBLIC_AUDIO_CHUNK_RETRY_DELAY_MS,
  caregiverAlertRefreshMs: process.env.EXPO_PUBLIC_CAREGIVER_ALERT_REFRESH_MS,
  vadDefaultThresholdDb: process.env.EXPO_PUBLIC_VAD_DEFAULT_THRESHOLD_DB,
  vadSilenceDurationMs: process.env.EXPO_PUBLIC_VAD_SILENCE_DURATION_MS,
  vadMinChunkMs: process.env.EXPO_PUBLIC_VAD_MIN_CHUNK_MS,
  vadMaxChunkMs: process.env.EXPO_PUBLIC_VAD_MAX_CHUNK_MS,
  vadPollIntervalMs: process.env.EXPO_PUBLIC_VAD_POLL_INTERVAL_MS,
  vadSpeechConfirmCount: process.env.EXPO_PUBLIC_VAD_SPEECH_CONFIRM_COUNT,
  vadBrokenMeteringThresholdDb: process.env.EXPO_PUBLIC_VAD_BROKEN_METERING_THRESHOLD_DB,
  vadBrokenMeteringFallbackMs: process.env.EXPO_PUBLIC_VAD_BROKEN_METERING_FALLBACK_MS,
  vadInvalidMeteringDb: process.env.EXPO_PUBLIC_VAD_INVALID_METERING_DB,
  vadCalibrationMinSamples: process.env.EXPO_PUBLIC_VAD_CALIBRATION_MIN_SAMPLES,
  vadCalibrationMinGapDb: process.env.EXPO_PUBLIC_VAD_CALIBRATION_MIN_GAP_DB,
  vadCalibrationMinThresholdDb: process.env.EXPO_PUBLIC_VAD_CALIBRATION_MIN_THRESHOLD_DB,
  vadCalibrationMaxThresholdDb: process.env.EXPO_PUBLIC_VAD_CALIBRATION_MAX_THRESHOLD_DB,
  vadCalibrationSpeechPercentile: process.env.EXPO_PUBLIC_VAD_CALIBRATION_SPEECH_PERCENTILE,
  vadCalibrationSilencePercentile: process.env.EXPO_PUBLIC_VAD_CALIBRATION_SILENCE_PERCENTILE,
  vadMeteringFloorDb: process.env.EXPO_PUBLIC_VAD_METERING_FLOOR_DB,
  ttsLanguage: process.env.EXPO_PUBLIC_TTS_LANGUAGE,
  ttsAssistantRate: process.env.EXPO_PUBLIC_TTS_ASSISTANT_RATE,
  ttsEpisodeRate: process.env.EXPO_PUBLIC_TTS_EPISODE_RATE,
  voiceSampleDurationMs: process.env.EXPO_PUBLIC_VOICE_SAMPLE_DURATION_MS,
  voiceSampleTickMs: process.env.EXPO_PUBLIC_VOICE_SAMPLE_TICK_MS,
};

function envString(name, value, fallback, { warnIfMissing = false } = {}) {
  if (value == null || String(value).trim() === "") {
    if (warnIfMissing) {
      console.warn(`[config] ${name} is not set; using ${fallback}`);
    }
    return fallback;
  }
  return String(value).trim();
}

function envInt(name, raw, fallback) {
  if (raw == null || String(raw).trim() === "") return fallback;
  const value = Number.parseInt(String(raw), 10);
  if (!Number.isFinite(value)) {
    console.warn(`[config] ${name} must be an integer; using ${fallback}`);
    return fallback;
  }
  return value;
}

function envFloat(name, raw, fallback) {
  if (raw == null || String(raw).trim() === "") return fallback;
  const value = Number.parseFloat(String(raw));
  if (!Number.isFinite(value)) {
    console.warn(`[config] ${name} must be a number; using ${fallback}`);
    return fallback;
  }
  return value;
}

const appConfig = {
  // Backend API and audio upload behavior.
  api: {
    baseUrl: envString("EXPO_PUBLIC_SERVER_URL", publicEnv.serverUrl, "http://localhost:8000", {
      warnIfMissing: true,
    }),
    audioChunkTimeoutMs: envInt("EXPO_PUBLIC_AUDIO_CHUNK_TIMEOUT_MS", publicEnv.audioChunkTimeoutMs, 30000),
    audioChunkMaxRetries: envInt("EXPO_PUBLIC_AUDIO_CHUNK_MAX_RETRIES", publicEnv.audioChunkMaxRetries, 1),
    audioChunkRetryDelayMs: envInt("EXPO_PUBLIC_AUDIO_CHUNK_RETRY_DELAY_MS", publicEnv.audioChunkRetryDelayMs, 1000),
  },

  // Caregiver dashboard behavior.
  caregiver: {
    alertRefreshMs: envInt("EXPO_PUBLIC_CAREGIVER_ALERT_REFRESH_MS", publicEnv.caregiverAlertRefreshMs, 10000),
  },

  // Patient recording VAD/chunking thresholds and calibration knobs.
  patientVad: {
    defaultThresholdDb: envFloat("EXPO_PUBLIC_VAD_DEFAULT_THRESHOLD_DB", publicEnv.vadDefaultThresholdDb, -45),
    silenceDurationMs: envInt("EXPO_PUBLIC_VAD_SILENCE_DURATION_MS", publicEnv.vadSilenceDurationMs, 1800),
    minChunkMs: envInt("EXPO_PUBLIC_VAD_MIN_CHUNK_MS", publicEnv.vadMinChunkMs, 2000),
    maxChunkMs: envInt("EXPO_PUBLIC_VAD_MAX_CHUNK_MS", publicEnv.vadMaxChunkMs, 15000),
    pollIntervalMs: envInt("EXPO_PUBLIC_VAD_POLL_INTERVAL_MS", publicEnv.vadPollIntervalMs, 250),
    speechConfirmCount: envInt("EXPO_PUBLIC_VAD_SPEECH_CONFIRM_COUNT", publicEnv.vadSpeechConfirmCount, 3),
    brokenMeteringThresholdDb: envFloat(
      "EXPO_PUBLIC_VAD_BROKEN_METERING_THRESHOLD_DB",
      publicEnv.vadBrokenMeteringThresholdDb,
      -155
    ),
    brokenMeteringFallbackMs: envInt(
      "EXPO_PUBLIC_VAD_BROKEN_METERING_FALLBACK_MS",
      publicEnv.vadBrokenMeteringFallbackMs,
      5000
    ),
    invalidMeteringDb: envFloat("EXPO_PUBLIC_VAD_INVALID_METERING_DB", publicEnv.vadInvalidMeteringDb, -155),
    calibrationMinSamples: envInt(
      "EXPO_PUBLIC_VAD_CALIBRATION_MIN_SAMPLES",
      publicEnv.vadCalibrationMinSamples,
      2
    ),
    calibrationMinGapDb: envFloat("EXPO_PUBLIC_VAD_CALIBRATION_MIN_GAP_DB", publicEnv.vadCalibrationMinGapDb, 5),
    calibrationMinThresholdDb: envFloat(
      "EXPO_PUBLIC_VAD_CALIBRATION_MIN_THRESHOLD_DB",
      publicEnv.vadCalibrationMinThresholdDb,
      -80
    ),
    calibrationMaxThresholdDb: envFloat(
      "EXPO_PUBLIC_VAD_CALIBRATION_MAX_THRESHOLD_DB",
      publicEnv.vadCalibrationMaxThresholdDb,
      -20
    ),
    calibrationSpeechPercentile: envFloat(
      "EXPO_PUBLIC_VAD_CALIBRATION_SPEECH_PERCENTILE",
      publicEnv.vadCalibrationSpeechPercentile,
      0.1
    ),
    calibrationSilencePercentile: envFloat(
      "EXPO_PUBLIC_VAD_CALIBRATION_SILENCE_PERCENTILE",
      publicEnv.vadCalibrationSilencePercentile,
      0.9
    ),
    meteringFloorDb: envFloat("EXPO_PUBLIC_VAD_METERING_FLOOR_DB", publicEnv.vadMeteringFloorDb, -160),
  },

  // Local text-to-speech playback settings.
  tts: {
    language: envString("EXPO_PUBLIC_TTS_LANGUAGE", publicEnv.ttsLanguage, "es-ES"),
    assistantRate: envFloat("EXPO_PUBLIC_TTS_ASSISTANT_RATE", publicEnv.ttsAssistantRate, 0.9),
    episodeRate: envFloat("EXPO_PUBLIC_TTS_EPISODE_RATE", publicEnv.ttsEpisodeRate, 0.85),
  },

  // Caregiver voice-sample recording UI.
  voiceSample: {
    durationMs: envInt("EXPO_PUBLIC_VOICE_SAMPLE_DURATION_MS", publicEnv.voiceSampleDurationMs, 10000),
    tickMs: envInt("EXPO_PUBLIC_VOICE_SAMPLE_TICK_MS", publicEnv.voiceSampleTickMs, 100),
  },
};

export default appConfig;
