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
import { sendAudioChunk } from "../services/api";

/* ── VAD tuning knobs ─────────────────────────────────────── */
const DEFAULT_THRESHOLD    = -45;   // initial dBFS threshold (before calibration)
const SILENCE_DURATION_MS  = 1800;  // quiet after speech → send (Spanish speakers pause mid-sentence)
const MIN_CHUNK_MS         = 2000;  // never send before 2 s
const MAX_CHUNK_MS         = 12000; // hard ceiling per chunk (faster-whisper is fast enough)
const POLL_INTERVAL_MS     = 250;   // how often to poll metering
const SPEECH_CONFIRM_COUNT = 3;     // consecutive polls above threshold to confirm speech (reduces false starts)

export default function PatientHomeScreen({ user, onLogout }) {
  const [listening, setListening] = useState(false);
  const [status, setStatus] = useState("Listo");
  const [lastReply, setLastReply] = useState(null);
  const recordingRef  = useRef(null);
  const abortRef      = useRef(null);
  const listeningRef  = useRef(false);
  const thresholdRef  = useRef(DEFAULT_THRESHOLD);  // calibrated threshold, persists across chunks
  const meteringRef   = useRef([]);                  // [{t: seconds, dB: number}] for current chunk

  /* ── start a metering-enabled recording ─────────────────── */
  const startRecording = async () => {
    try {
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
      console.error("Error starting recording:", e);
    }
  };

  /* ── stop current recording and send to backend ─────────── */
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
        const result = await sendAudioChunk(uri);
        calibrateThreshold(metering, result.segments || []);
        if (result.transcript) {
          setStatus(`Escuchado: "${result.transcript.substring(0, 60)}..."`);
        }
        if (result.episode && result.reply_text) {
          setLastReply(result.reply_text);
          Speech.speak(result.reply_text, { language: "es-ES", rate: 0.85 });
          setStatus("⚠️ Episodio detectado - Tu responsable ha sido avisado");
        }
      }
    } catch (e) {
      console.error("Error processing chunk:", e);
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
      if (m.dB <= -155) continue; // skip broken readings
      const inSpeech = segments.some(s => m.t >= s.start && m.t <= s.end);
      if (inSpeech) speechSamples.push(m.dB);
      else silenceSamples.push(m.dB);
    }

    if (speechSamples.length < 2 || silenceSamples.length < 2) return;

    // Speech floor = 10th percentile of speech readings (robustly low)
    speechSamples.sort((a, b) => a - b);
    const speechFloor = speechSamples[Math.floor(speechSamples.length * 0.1)];

    // Silence level = 90th percentile of silence readings (robustly high)
    silenceSamples.sort((a, b) => a - b);
    const silenceLevel = silenceSamples[Math.floor(silenceSamples.length * 0.9)];

    // Only calibrate if there's a clear gap (at least 5 dB)
    if (speechFloor - silenceLevel < 5) {
      console.log(`[CAL] Gap too small: speech floor ${speechFloor.toFixed(0)}, silence ${silenceLevel.toFixed(0)} — keeping threshold ${thresholdRef.current.toFixed(0)}`);
      return;
    }

    const newThreshold = (speechFloor + silenceLevel) / 2;
    // Clamp to reasonable range
    const clamped = Math.max(-80, Math.min(-20, newThreshold));
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
      let silenceSince = null;
      let pollCount = 0;
      let peakDb = -160;

      const interval = setInterval(async () => {
        if (resolved || !recordingRef.current) return;

        const elapsed = Date.now() - startTime;
        pollCount++;

        let dB = -160;
        try {
          const st = await recordingRef.current.getStatusAsync();
          if (st.metering != null) dB = st.metering;
        } catch (_) { return; }

        if (dB > peakDb) peakDb = dB;

        // Store metering sample for calibration (time relative to recording start)
        meteringRef.current.push({ t: elapsed / 1000, dB });

        const thr = thresholdRef.current;

        // Debug on-screen
        setStatus(`🎙 dB:${dB.toFixed(0)} thr:${thr.toFixed(0)} ${speechDetected ? '🔴HABLA' : '⚪'} ${(elapsed/1000).toFixed(1)}s`);

        if (pollCount % 4 === 0) {
          console.log(`[VAD] dB=${dB.toFixed(1)} thr=${thr.toFixed(0)} speech=${speechDetected} count=${speechCount} peak=${peakDb.toFixed(0)} ${(elapsed/1000).toFixed(1)}s`);
        }

        // Metering broken fallback
        if (elapsed > 2000 && peakDb <= -155) {
          if (elapsed >= 5000) {
            console.log("[VAD] Metering unavailable — sending 5s fallback chunk");
            done("timeout");
          }
          return;
        }

        const isSpeech = dB > thr;

        if (isSpeech) {
          speechCount++;
          silenceSince = null;
          if (speechCount >= SPEECH_CONFIRM_COUNT) speechDetected = true;
        } else {
          speechCount = 0;
        }

        if (!isSpeech && speechDetected) {
          if (!silenceSince) silenceSince = Date.now();
          if (Date.now() - silenceSince >= SILENCE_DURATION_MS && elapsed >= MIN_CHUNK_MS) {
            console.log(`[VAD] Silence after speech — sending (${(elapsed/1000).toFixed(1)}s)`);
            done("silence");
            return;
          }
        }

        if (elapsed >= MAX_CHUNK_MS) {
          done(peakDb > thr ? "timeout" : "quiet");
        }
      }, POLL_INTERVAL_MS);

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
        const result = await sendAudioChunk(uri);
        calibrateThreshold(metering, result.segments || []);

        if (result.transcript) {
          setStatus(`Escuchado: "${result.transcript.substring(0, 60)}..."`);
        }
        if (result.episode && result.reply_text) {
          setLastReply(result.reply_text);
          Speech.speak(result.reply_text, { language: "es-ES", rate: 0.85 });
          setStatus("⚠️ Episodio detectado - Tu responsable ha sido avisado");
        } else if (listening) {
          setStatus("Escuchando...");
        }
      } catch (e) {
        console.error("Error processing chunk:", e);
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
    };
  }, []);

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.greeting}>Hola, {user.full_name}</Text>
        <Pressable onPress={onLogout}>
          <Text style={styles.logout}>Salir</Text>
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
