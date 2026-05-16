import React, { useState, useRef, useEffect } from "react";
import { View, Text, Pressable, StyleSheet, Alert } from "react-native";
import { Audio } from "expo-av";
import { getAlertAudioUrl, getAuthHeader } from "../services/api";

function renderTaggedTranscript(text) {
  if (!text) return null;
  const parts = text
    .split(/(\[PACIENTE\?\]|\[PACIENTE\]|\[OTRO\]|\[ASISTENTE\])/g)
    .filter((p) => p.trim());
  const blocks = [];
  let currentTag = null;
  for (const part of parts) {
    if (part === "[PACIENTE]" || part === "[PACIENTE?]" || part === "[OTRO]" || part === "[ASISTENTE]") {
      currentTag = part;
      continue;
    }
    blocks.push({ tag: currentTag, text: part.trim() });
  }
  if (!blocks.length) {
    return <Text style={styles.transcriptPlain}>{text}</Text>;
  }
  return blocks.map((b, i) => (
    <View
      key={i}
      style={[
        styles.transcriptBlock,
        b.tag === "[PACIENTE]"
          ? styles.transcriptPatient
          : b.tag === "[PACIENTE?]"
            ? styles.transcriptMaybePatient
            : b.tag === "[ASISTENTE]"
              ? styles.transcriptAssistant
              : styles.transcriptOther,
      ]}
    >
      <Text style={styles.transcriptTag}>{b.tag || ""}</Text>
      <Text style={styles.transcriptText}>{b.text}</Text>
    </View>
  ));
}

export default function AlertCard({ alert, patientName, isNew, onAck }) {
  const [expanded, setExpanded] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [loadingAudio, setLoadingAudio] = useState(false);
  const soundRef = useRef(null);

  useEffect(() => {
    return () => {
      if (soundRef.current) {
        soundRef.current.unloadAsync().catch(() => {});
        soundRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!expanded && soundRef.current) {
      soundRef.current.unloadAsync().catch(() => {});
      soundRef.current = null;
      setPlaying(false);
    }
  }, [expanded]);

  const togglePlayback = async () => {
    try {
      if (soundRef.current) {
        if (playing) {
          await soundRef.current.pauseAsync();
          setPlaying(false);
        } else {
          await soundRef.current.playAsync();
          setPlaying(true);
        }
        return;
      }
      setLoadingAudio(true);
      const { sound } = await Audio.Sound.createAsync(
        { uri: getAlertAudioUrl(alert.id), headers: getAuthHeader() },
        { shouldPlay: true },
        (status) => {
          if (status.didJustFinish) {
            setPlaying(false);
          }
        }
      );
      soundRef.current = sound;
      setPlaying(true);
    } catch (e) {
      Alert.alert("Audio", "No se puede reproducir el audio: " + (e.message || e));
    } finally {
      setLoadingAudio(false);
    }
  };

  const hasDetails = alert.transcript_text || alert.audio_url;

  return (
    <View style={[styles.alertCard, isNew && styles.alertNew]}>
      <View style={styles.alertHeader}>
        <Text style={styles.alertPatient}>{patientName}</Text>
        <Text style={styles.alertSeverity}>Sev: {alert.severity}/5</Text>
      </View>
      <Text style={styles.alertReason}>{alert.reason}</Text>
      {alert.llm_response ? (
        <Text style={styles.alertLlm}>Respuesta IA: {alert.llm_response}</Text>
      ) : null}

      <View style={styles.alertFooter}>
        <Text style={styles.alertTime}>
          {new Date(alert.created_at).toLocaleString("es-ES")}
        </Text>
        {isNew && onAck ? (
          <Pressable style={styles.ackBtn} onPress={() => onAck(alert.id)}>
            <Text style={styles.ackText}>✓ Aceptar</Text>
          </Pressable>
        ) : null}
      </View>

      {hasDetails ? (
        <Pressable onPress={() => setExpanded((v) => !v)} style={styles.expandRow}>
          <Text style={styles.expandLabel}>
            {expanded ? "▴ Ocultar detalles" : "▾ Ver transcripción" + (alert.audio_url ? " / audio" : "")}
          </Text>
        </Pressable>
      ) : null}

      {expanded ? (
        <View style={styles.detailsBox}>
          {alert.transcript_text ? (
            <View>{renderTaggedTranscript(alert.transcript_text)}</View>
          ) : (
            <Text style={styles.noData}>Sin transcripción guardada.</Text>
          )}
          {alert.audio_url ? (
            <Pressable style={styles.audioBtn} onPress={togglePlayback} disabled={loadingAudio}>
              <Text style={styles.audioBtnText}>
                {loadingAudio ? "Cargando…" : playing ? "⏸ Pausar" : "▶ Reproducir audio"}
              </Text>
            </Pressable>
          ) : (
            <Text style={styles.noData}>Audio no disponible.</Text>
          )}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  alertCard: {
    backgroundColor: "#fff",
    borderRadius: 14,
    padding: 14,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: "#E0E0E0",
  },
  alertNew: { borderLeftWidth: 4, borderLeftColor: "#E74C3C" },
  alertHeader: { flexDirection: "row", justifyContent: "space-between", marginBottom: 6 },
  alertPatient: { fontWeight: "700", fontSize: 15 },
  alertSeverity: { color: "#E74C3C", fontWeight: "600" },
  alertReason: { fontSize: 14, marginBottom: 6 },
  alertLlm: { fontSize: 13, color: "#555", fontStyle: "italic", marginBottom: 6 },
  alertFooter: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  alertTime: { fontSize: 12, color: "#999" },
  ackBtn: {
    backgroundColor: "#27AE60",
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  ackText: { color: "#fff", fontWeight: "600", fontSize: 13 },

  expandRow: { marginTop: 8 },
  expandLabel: { color: "#4A90D9", fontSize: 13, fontWeight: "600" },
  detailsBox: {
    marginTop: 10,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: "#EEE",
  },
  transcriptBlock: {
    borderRadius: 8,
    padding: 8,
    marginBottom: 6,
  },
  transcriptPatient: { backgroundColor: "#E8F1FB" },
  transcriptMaybePatient: { backgroundColor: "#FFF5D9" },
  transcriptAssistant: { backgroundColor: "#ECE8FB" },
  transcriptOther: { backgroundColor: "#F3F3F3" },
  transcriptTag: { fontSize: 11, fontWeight: "700", color: "#666", marginBottom: 2 },
  transcriptText: { fontSize: 14, color: "#222" },
  transcriptPlain: { fontSize: 14, color: "#222" },
  noData: { fontSize: 13, color: "#999", fontStyle: "italic", marginTop: 4 },
  audioBtn: {
    marginTop: 10,
    backgroundColor: "#4A90D9",
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
  },
  audioBtnText: { color: "#fff", fontWeight: "600", fontSize: 14 },
});
