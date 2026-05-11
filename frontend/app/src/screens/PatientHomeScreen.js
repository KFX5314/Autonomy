/**
 * Patient Home - continuous recording with adaptive silence detection.
 *
 * Uses a calibrated dBFS threshold that auto-adjusts after each chunk
 * by analysing which metering readings correspond to speech vs silence
 * (from Whisper's segment timestamps).
 */
import React, { useRef, useState, useEffect, useCallback } from "react";
import { View, Text, Pressable, StyleSheet, Alert, AppState } from "react-native";
import { Audio } from "expo-av";
import * as Speech from "expo-speech";
import { useFocusEffect } from "@react-navigation/native";
import appConfig from "../config/appConfig";
import { getMyPatientSettings, sendAudioChunk } from "../services/api";
import { loadPatientTtsEnabled } from "../services/session";

/* ── VAD tuning knobs ─────────────────────────────────────── */
const { patientVad, tts } = appConfig;

export default function PatientHomeScreen({ user, onLogout, onOpenSettings }) {
  const [listening, setListening] = useState(false);
  const [status, setStatus] = useState("Listo");
  const [lastReply, setLastReply] = useState(null);
  const [caregiverTtsEnabled, setCaregiverTtsEnabled] = useState(true);
  const [localTtsEnabled, setLocalTtsEnabled] = useState(true);
  const recordingRef  = useRef(null);
  const abortRef      = useRef(null);
  const listeningRef  = useRef(false);
  const thresholdRef  = useRef(patientVad.defaultThresholdDb);  // calibrated threshold, persists across chunks
  const meteringRef   = useRef([]);                  // [{t: seconds, dB: number}] for current chunk
  const recentTtsRef  = useRef(null);                // { text, markedAt } for assistant echo tagging
  const userId = user?.user_id || user?.id;
  const ttsPlaybackEnabled = caregiverTtsEnabled && localTtsEnabled;

  useFocusEffect(
    useCallback(() => {
      let active = true;
      (async () => {
        const localEnabled = await loadPatientTtsEnabled(userId);
        if (active) setLocalTtsEnabled(localEnabled);
        try {
          const settings = await getMyPatientSettings();
          if (active) setCaregiverTtsEnabled(settings.tts_enabled !== false);
        } catch (e) {
          console.warn("Could not load patient TTS settings:", e?.message || e);
        }
      })();
      return () => {
        active = false;
      };
    }, [userId])
  );

  /* ── start a metering-enabled recording ─────────────────── */
  const startRecording = async () => {
    try {
      // Clean up any stale recording that wasn't properly released
      // (can happen on re-login, app resume, or abort race conditions).
      if (recordingRef.current) {
        try {
          await recordingRef.current.stopAndUnloadAsync();
        } catch (_) {}
        recordingRef.current = null;
      }

      const perm = await Audio.requestPermissionsAsync();
      if (!perm.granted) {
        Alert.alert("Permiso necesario", "Se necesita acceso al micrófono.");
        return;
      }
      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
      });
      meteringRef.current = [];
      const { recording } = await Audio.Recording.createAsync(
        { ...Audio.RecordingOptionsPresets.HIGH_QUALITY, isMeteringEnabled: true },
      );
      recordingRef.current = recording;
    } catch (e) {
      console.warn("[REC] Error starting recording:", e.message);
    }
  };

  /* ── stop current recording and send to backend ─────────── */
  const markRecentTts = useCallback((text) => {
    if (!text) return;
    recentTtsRef.current = { text, markedAt: Date.now() };
  }, []);

  const getRecentTtsMetadata = useCallback(() => {
    const recent = recentTtsRef.current;
    if (!recent?.text || !recent.markedAt) return {};
    const ageMs = Date.now() - recent.markedAt;
    if (ageMs < 0 || ageMs > tts.echoMetadataWindowMs) return {};
    return { recentTtsText: recent.text, recentTtsAgeMs: ageMs };
  }, []);

  const speakReply = useCallback((text, rate) => {
    if (!text) return;
    setLastReply(text);
    if (!ttsPlaybackEnabled) return;
    markRecentTts(text);
    Speech.speak(text, {
      language: tts.language,
      rate,
      onStart: () => markRecentTts(text),
      onDone: () => markRecentTts(text),
      onStopped: () => markRecentTts(text),
      onError: () => markRecentTts(text),
    });
  }, [markRecentTts, ttsPlaybackEnabled]);

  const stopAndSend = async () => {
    const recording = recordingRef.current;
    if (!recording) return;
    const metering = [...meteringRef.current];
    try {
      await recording.stopAndUnloadAsync();
      const uri = recording.getURI();
      recordingRef.current = null;
      if (uri) {
        setStatus("Procesando...");
        const result = await sendAudioChunk(uri, getRecentTtsMetadata());
        calibrateThreshold(metering, result.segments || []);
        if (result.transcript) {
          setStatus(`Escuchado: "${result.transcript.substring(0, 60)}..."`);
        }
        if (result.mode === "assistant" && result.reply_text) {
          speakReply(result.reply_text, tts.assistantRate);
          setStatus(`🗣 ${result.reply_text.substring(0, 80)}`);
        } else if (result.episode && result.reply_text) {
          speakReply(result.reply_text, tts.episodeRate);
          setStatus("⚠️ Episodio detectado - Tu responsable ha sido avisado");
        }
      }
    } catch (e) {
      if (e.message === "Network request failed" || e.name === "AbortError") {
        console.warn("[SEND] Chunk send failed (network):", e.message);
        setStatus("Sin conexion - reintentando...");
      } else {
        console.error("Error processing chunk:", e);
      }
    }
  };

  /* ── discard recording without sending ──────────────────── */
  const discardRecording = async () => {
    const recording = recordingRef.current;
    if (!recording) return;
    try { await recording.stopAndUnloadAsync(); } catch (_) {}
    recordingRef.current = null;
  };

  /* ── calibrate threshold using Whisper segments + metering ─
   * speech samples: metering during Whisper segments → lowest = speech floor
   * silence samples: metering outside Whisper segments → typical = silence level
   * threshold = midpoint between silence level and speech floor
   */
  const calibrateThreshold = (metering, segments) => {
    if (!metering.length || !segments.length) return;

    const speechSamples = [];
    const silenceSamples = [];

    for (const m of metering) {
      if (m.dB <= patientVad.invalidMeteringDb) continue; // skip broken readings
      const inSpeech = segments.some(s => m.t >= s.start && m.t <= s.end);
      if (inSpeech) speechSamples.push(m.dB);
      else silenceSamples.push(m.dB);
    }

    if (
      speechSamples.length < patientVad.calibrationMinSamples ||
      silenceSamples.length < patientVad.calibrationMinSamples
    ) return;

    // Speech floor = low percentile of speech readings (robustly low)
    speechSamples.sort((a, b) => a - b);
    const speechIndex = Math.min(
      speechSamples.length - 1,
      Math.max(0, Math.floor(speechSamples.length * patientVad.calibrationSpeechPercentile))
    );
    const speechFloor = speechSamples[speechIndex];

    // Silence level = high percentile of silence readings (robustly high)
    silenceSamples.sort((a, b) => a - b);
    const silenceIndex = Math.min(
      silenceSamples.length - 1,
      Math.max(0, Math.floor(silenceSamples.length * patientVad.calibrationSilencePercentile))
    );
    const silenceLevel = silenceSamples[silenceIndex];

    // Only calibrate if there's a clear speech/silence gap.
    if (speechFloor - silenceLevel < patientVad.calibrationMinGapDb) {
      console.log(`[CAL] Gap too small: speech floor ${speechFloor.toFixed(0)}, silence ${silenceLevel.toFixed(0)} — keeping threshold ${thresholdRef.current.toFixed(0)}`);
      return;
    }

    const newThreshold = (speechFloor + silenceLevel) / 2;
    // Clamp to reasonable range
    const clamped = Math.max(
      patientVad.calibrationMinThresholdDb,
      Math.min(patientVad.calibrationMaxThresholdDb, newThreshold)
    );
    console.log(`[CAL] speech floor=${speechFloor.toFixed(0)} silence=${silenceLevel.toFixed(0)} → threshold: ${thresholdRef.current.toFixed(0)} → ${clamped.toFixed(0)}`);
    thresholdRef.current = clamped;
  };

  /* ── adaptive silence-detection wait ────────────────────── */
  const waitForSilenceOrTimeout = (signal) =>
    new Promise((resolve) => {
      let resolved = false;
      const done = (reason) => {
        if (resolved) return;
        resolved = true;
        clearInterval(interval);
        resolve(reason);
      };

      const startTime = Date.now();
      let speechDetected = false;
      let speechCount = 0;
      let speechRunStartedAt = null;
      let speechStartedAt = null;
      let silenceSince = null;
      let pollCount = 0;
      let peakDb = patientVad.meteringFloorDb;

      const interval = setInterval(async () => {
        if (resolved || !recordingRef.current) return;

        const elapsed = Date.now() - startTime;
        pollCount++;

        let dB = patientVad.meteringFloorDb;
        try {
          const st = await recordingRef.current.getStatusAsync();
          if (st.metering != null) dB = st.metering;
        } catch (_) { return; }

        if (dB > peakDb) peakDb = dB;

        // Store metering sample for calibration (time relative to recording start)
        meteringRef.current.push({ t: elapsed / 1000, dB });

        const thr = thresholdRef.current;
        const speechElapsed = speechStartedAt ? Date.now() - speechStartedAt : 0;

        // Debug on-screen
        setStatus(`🎙 dB:${dB.toFixed(0)} thr:${thr.toFixed(0)} ${speechDetected ? '🔴HABLA' : '⚪'} ${((speechStartedAt ? speechElapsed : elapsed) / 1000).toFixed(1)}s`);

        if (pollCount % 4 === 0) {
          console.log(`[VAD] dB=${dB.toFixed(1)} thr=${thr.toFixed(0)} speech=${speechDetected} count=${speechCount} peak=${peakDb.toFixed(0)} rec=${(elapsed / 1000).toFixed(1)}s speech=${(speechElapsed / 1000).toFixed(1)}s`);
        }

        // Metering broken fallback
        if (elapsed > patientVad.minChunkMs && peakDb <= patientVad.brokenMeteringThresholdDb) {
          if (elapsed >= patientVad.brokenMeteringFallbackMs) {
            console.log(
              `[VAD] Metering unavailable - sending ${patientVad.brokenMeteringFallbackMs / 1000}s fallback chunk`
            );
            done("timeout");
          }
          return;
        }

        const isSpeech = dB > thr;

        if (isSpeech) {
          if (speechCount === 0) speechRunStartedAt = Date.now();
          speechCount++;
          silenceSince = null;
          if (!speechDetected && speechCount >= patientVad.speechConfirmCount) {
            speechDetected = true;
            speechStartedAt = speechRunStartedAt || Date.now();
            console.log(`[VAD] Speech confirmed - max timer starts at ${((speechStartedAt - startTime) / 1000).toFixed(1)}s`);
          }
        } else {
          speechCount = 0;
          if (!speechDetected) speechRunStartedAt = null;
        }

        if (!isSpeech && speechDetected) {
          if (!silenceSince) silenceSince = Date.now();
          if (Date.now() - silenceSince >= patientVad.silenceDurationMs && elapsed >= patientVad.minChunkMs) {
            console.log(`[VAD] Silence after speech — sending (${(elapsed/1000).toFixed(1)}s)`);
            done("silence");
            return;
          }
        }

        if (speechDetected && speechStartedAt && Date.now() - speechStartedAt >= patientVad.maxChunkMs) {
          console.log(`[VAD] Max speech window reached - sending (${(elapsed / 1000).toFixed(1)}s recording, ${((Date.now() - speechStartedAt) / 1000).toFixed(1)}s since speech)`);
          done("timeout");
          return;
        }

        if (!speechDetected && speechCount === 0 && elapsed >= patientVad.maxChunkMs) {
          done("quiet");
        }
      }, patientVad.pollIntervalMs);

      signal.addEventListener("abort", () => done("aborted"), { once: true });
    });

  /* ── send a finished chunk (fire-and-forget, max 1 in-flight) ── */
  const sendingRef = useRef(false);
  const sendInBackground = (uri, metering) => {
    if (sendingRef.current) {
      console.log("[VAD] Skipping send — previous chunk still in-flight");
      return;
    }
    sendingRef.current = true;
    (async () => {
      try {
        const result = await sendAudioChunk(uri, getRecentTtsMetadata());
        calibrateThreshold(metering, result.segments || []);

        if (result.transcript) {
          setStatus(`Escuchado: "${result.transcript.substring(0, 60)}..."`);
        }
        if (result.mode === "assistant" && result.reply_text) {
          speakReply(result.reply_text, tts.assistantRate);
          setStatus(`🗣 ${result.reply_text.substring(0, 80)}`);
        } else if (result.episode && result.reply_text) {
          speakReply(result.reply_text, tts.episodeRate);
          setStatus("⚠️ Episodio detectado - Tu responsable ha sido avisado");
        } else if (listening) {
          setStatus("Escuchando...");
        }
      } catch (e) {
        if (e.message === "Network request failed" || e.name === "AbortError") {
          console.warn("[SEND] Chunk send failed (network):", e.message);
          setStatus("Sin conexion - reintentando...");
        } else {
          console.error("Error processing chunk:", e);
        }
      } finally {
        sendingRef.current = false;
      }
    })();
  };

  /* ── main loop (overlaps recording with sending) ────────── */
  const recordLoop = async (signal) => {
    while (!signal.aborted) {
      await startRecording();
      const reason = await waitForSilenceOrTimeout(signal);
      if (signal.aborted) break;

      if (reason === "quiet") {
        await discardRecording();
        continue;
      }

      const recording = recordingRef.current;
      if (!recording) continue;
      const metering = [...meteringRef.current]; // snapshot for calibration
      try {
        await recording.stopAndUnloadAsync();
        const uri = recording.getURI();
        recordingRef.current = null;
        if (uri) sendInBackground(uri, metering);
      } catch (e) {
        console.error("Error stopping recording:", e);
        recordingRef.current = null;
      }
    }
  };

  const startListening = useCallback(async () => {
    const controller = new AbortController();
    abortRef.current = controller;
    setListening(true);
    listeningRef.current = true;
    setStatus("Escuchando...");
    recordLoop(controller.signal);
  }, []);

  const stopListening = useCallback(async () => {
    abortRef.current?.abort();
    listeningRef.current = false;
    await stopAndSend();
    setListening(false);
    setStatus("Listo");
  }, []);

  /* ── AppState: pause recording when phone locks / backgrounds ── */
  useEffect(() => {
    const subscription = AppState.addEventListener("change", async (nextState) => {
      if (nextState !== "active") {
        if (abortRef.current) {
          console.log("[VAD] App backgrounded — pausing recording");
          abortRef.current.abort();
          await discardRecording();
        }
      } else if (listeningRef.current) {
        console.log("[VAD] App foregrounded — resuming recording");
        const controller = new AbortController();
        abortRef.current = controller;
        setStatus("Escuchando...");
        recordLoop(controller.signal);
      }
    });
    return () => {
      subscription.remove();
      abortRef.current?.abort();
      // Release the recording singleton on unmount (e.g. re-login)
      discardRecording();
    };
  }, []);

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.greeting}>Hola, {user.full_name}</Text>
        <Pressable onPress={onOpenSettings} hitSlop={10} style={styles.gearBtn}>
          <Text style={styles.gear}>⚙︎</Text>
        </Pressable>
      </View>

      <View style={styles.center}>
        <Pressable
          style={[styles.recordButton, listening && styles.recordButtonActive]}
          onPress={listening ? stopListening : startListening}
        >
          <Text style={styles.recordIcon}>{listening ? "⏹" : "🎙"}</Text>
          <Text style={styles.recordLabel}>
            {listening ? "Detener" : "Activar escucha"}
          </Text>
        </Pressable>

        <Text style={styles.status}>{status}</Text>

        {lastReply && (
          <View style={styles.replyBox}>
            <Text style={styles.replyTitle}>Último mensaje del asistente:</Text>
            <Text style={styles.replyText}>{lastReply}</Text>
          </View>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#F5F7FA", padding: 20 },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 40,
    marginBottom: 20,
  },
  greeting: { fontSize: 22, fontWeight: "700" },
  logout: { color: "#E74C3C", fontSize: 16 },
  gearBtn: { paddingHorizontal: 6, paddingVertical: 4 },
  gear: { fontSize: 24, color: "#555" },
  center: { flex: 1, justifyContent: "center", alignItems: "center" },
  recordButton: {
    width: 180,
    height: 180,
    borderRadius: 90,
    backgroundColor: "#4A90D9",
    justifyContent: "center",
    alignItems: "center",
    elevation: 8,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
  },
  recordButtonActive: { backgroundColor: "#E74C3C" },
  recordIcon: { fontSize: 48 },
  recordLabel: { color: "#fff", fontSize: 16, fontWeight: "600", marginTop: 8 },
  status: { marginTop: 24, fontSize: 16, color: "#555", textAlign: "center", paddingHorizontal: 20 },
  replyBox: {
    marginTop: 24,
    backgroundColor: "#fff",
    borderRadius: 16,
    padding: 16,
    width: "100%",
    borderLeftWidth: 4,
    borderLeftColor: "#4A90D9",
  },
  replyTitle: { fontSize: 14, fontWeight: "600", color: "#4A90D9", marginBottom: 8 },
  replyText: { fontSize: 16, lineHeight: 22 },
});
