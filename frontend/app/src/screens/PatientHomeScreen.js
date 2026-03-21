/**
 * Patient Home — continuous recording + episode alert display.
 */
import React, { useRef, useState, useEffect, useCallback } from "react";
import { View, Text, Pressable, StyleSheet, Alert } from "react-native";
import { Audio } from "expo-av";
import * as Speech from "expo-speech";
import { sendAudioChunk } from "../services/api";

const CHUNK_DURATION_MS = 15000; // 15 seconds per chunk

export default function PatientHomeScreen({ user, onLogout }) {
  const [listening, setListening] = useState(false);
  const [status, setStatus] = useState("Listo");
  const [lastReply, setLastReply] = useState(null);
  const recordingRef = useRef(null);
  const intervalRef = useRef(null);

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
        Audio.RecordingOptionsPresets.HIGH_QUALITY
      );
      recordingRef.current = recording;
    } catch (e) {
      console.error("Error starting recording:", e);
    }
  };

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
        // Speak the response to the patient
        Speech.speak(result.reply_text, { language: "es-ES", rate: 0.85 });
        setStatus("⚠️ Episodio detectado — Tu responsable ha sido avisado");
      } else {
        setStatus("Escuchando...");
      }
    } catch (e) {
      console.error("Error processing chunk:", e);
      setStatus("Error procesando audio");
    }
  };

  const startListening = useCallback(async () => {
    setListening(true);
    setStatus("Escuchando...");
    await startRecording();

    // Cycle: record → send → record every CHUNK_DURATION_MS
    intervalRef.current = setInterval(async () => {
      await stopAndSend();
      await startRecording();
    }, CHUNK_DURATION_MS);
  }, []);

  const stopListening = useCallback(async () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    await stopAndSend();
    setListening(false);
    setStatus("Listo");
  }, []);

  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
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
