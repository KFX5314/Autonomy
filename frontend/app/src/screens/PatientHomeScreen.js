/**
 * Patient Home - continuous recording with adaptive silence detection.
 *
 * Instead of fixed 15 s chunks, we track a rolling ambient-noise baseline
 * via expo-av metering.  When speech raises the energy above baseline and
 * then drops back for SILENCE_DURATION_MS, the chunk is sent immediately.
 * MAX_CHUNK_MS (15 s) is kept as a hard ceiling.
 */
import React, { useRef, useState, useEffect, useCallback } from "react";
import { View, Text, Pressable, StyleSheet, Alert } from "react-native";
import { Audio } from "expo-av";
import * as Speech from "expo-speech";
import { sendAudioChunk } from "../services/api";

/* ── VAD tuning knobs ─────────────────────────────────────── */
const SPEECH_THRESHOLD_DB = 8;      // dB above baseline → "speech"
const SILENCE_DURATION_MS = 1500;   // quiet after speech → send
const MIN_CHUNK_MS        = 2000;   // never send before 2 s
const MAX_CHUNK_MS        = 15000;  // hard ceiling per chunk
const METER_INTERVAL_MS   = 250;    // metering poll rate
const BASELINE_ALPHA      = 0.10;   // EMA smoothing for baseline

export default function PatientHomeScreen({ user, onLogout }) {
  const [listening, setListening] = useState(false);
  const [status, setStatus] = useState("Listo");
  const [lastReply, setLastReply] = useState(null);
  const recordingRef = useRef(null);
  const abortRef     = useRef(null);   // AbortController
  const meteringRef  = useRef(-160);   // latest dB from expo-av

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

      const { recording } = await Audio.Recording.createAsync(
        { ...Audio.RecordingOptionsPresets.HIGH_QUALITY, isMeteringEnabled: true },
        (s) => { if (s.metering != null) meteringRef.current = s.metering; },
        METER_INTERVAL_MS,
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

    try {
      await recording.stopAndUnloadAsync();
      const uri = recording.getURI();
      recordingRef.current = null;

      setStatus("Procesando...");
      const result = await sendAudioChunk(uri);

      if (result.transcript) {
        setStatus(`Escuchado: "${result.transcript.substring(0, 60)}..."`);
      }

      if (result.episode && result.reply_text) {
        setLastReply(result.reply_text);
        Speech.speak(result.reply_text, { language: "es-ES", rate: 0.85 });
        setStatus("⚠️ Episodio detectado - Tu responsable ha sido avisado");
      } else {
        setStatus("Escuchando...");
      }
    } catch (e) {
      console.error("Error processing chunk:", e);
      setStatus("Escuchando...");
    }
  };

  /* ── discard recording without sending ──────────────────── */
  const discardRecording = async () => {
    const recording = recordingRef.current;
    if (!recording) return;
    try {
      await recording.stopAndUnloadAsync();
    } catch (_) { /* already stopped */ }
    recordingRef.current = null;
  };

  /* ── adaptive silence-detection wait ────────────────────── *
   * Resolves with:
   *   "silence"  – speech detected then quiet for SILENCE_DURATION_MS
   *   "timeout"  – MAX_CHUNK_MS reached (with speech)
   *   "quiet"    – MAX_CHUNK_MS reached with no speech at all
   *   "aborted"  – user pressed stop
   */
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
      let baseline = null;
      let speechDetected = false;
      let silenceSince = null;

      const interval = setInterval(() => {
        const elapsed = Date.now() - startTime;
        const dB = meteringRef.current;

        // first reading seeds the baseline
        if (baseline === null) { baseline = dB; return; }

        const isSpeech = dB > baseline + SPEECH_THRESHOLD_DB;

        // adapt baseline only during non-speech
        if (!isSpeech) {
          baseline = baseline * (1 - BASELINE_ALPHA) + dB * BASELINE_ALPHA;
        }

        if (isSpeech) {
          speechDetected = true;
          silenceSince = null;
        } else if (speechDetected) {
          if (!silenceSince) silenceSince = Date.now();
          if (Date.now() - silenceSince >= SILENCE_DURATION_MS &&
              elapsed >= MIN_CHUNK_MS) {
            done("silence");
            return;
          }
        }

        if (elapsed >= MAX_CHUNK_MS) {
          done(speechDetected ? "timeout" : "quiet");
        }
      }, METER_INTERVAL_MS);

      signal.addEventListener("abort", () => done("aborted"), { once: true });
    });

  /* ── main loop ──────────────────────────────────────────── */
  const recordLoop = async (signal) => {
    while (!signal.aborted) {
      await startRecording();
      const reason = await waitForSilenceOrTimeout(signal);
      if (signal.aborted) break;

      if (reason === "quiet") {
        // no speech in this window — discard & loop
        await discardRecording();
        continue;
      }
      await stopAndSend();
    }
  };

  const startListening = useCallback(async () => {
    const controller = new AbortController();
    abortRef.current = controller;
    setListening(true);
    setStatus("Escuchando...");
    recordLoop(controller.signal);
  }, []);

  const stopListening = useCallback(async () => {
    abortRef.current?.abort();
    await stopAndSend();
    setListening(false);
    setStatus("Listo");
  }, []);

  useEffect(() => {
    return () => {
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
