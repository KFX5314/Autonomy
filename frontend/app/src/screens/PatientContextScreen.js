/**
 * Edit patient context - caregiver edits trigger phrases, risk rules, profile.
 */
import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  View,
  Text,
  TextInput,
  Pressable,
  ScrollView,
  StyleSheet,
  Alert,
  Animated,
} from "react-native";
import { Audio } from "expo-av";
import { getPatientContext, updatePatientContext, uploadVoiceSample } from "../services/api";

export default function PatientContextScreen({ patient, onBack }) {
  const [context, setContext] = useState(null);
  const [loading, setLoading] = useState(true);

  // Editable fields
  const [preferredName, setPreferredName] = useState("");
  const [address, setAddress] = useState("");
  const [caregiverNames, setCaregiverNames] = useState("");
  const [medicalNotes, setMedicalNotes] = useState("");
  const [triggerPhrases, setTriggerPhrases] = useState("");
  const [riskRules, setRiskRules] = useState("");
  const [recording, setRecording] = useState(null);
  const [voiceStatus, setVoiceStatus] = useState(null); // null | "recording" | "uploading" | "done"
  const [voiceProgress, setVoiceProgress] = useState(0); // 0-1
  const progressAnim = useRef(new Animated.Value(0)).current;
  const timerRef = useRef(null);
  const recordingRef = useRef(null);

  const VOICE_DURATION_MS = 10000; // 10 seconds
  const TICK_MS = 100;

  useEffect(() => {
    loadContext();
  }, []);

  // Clean up timer on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const loadContext = async () => {
    try {
      const data = await getPatientContext(patient.id);
      const ctx = data.context_json;
      setContext(ctx);

      const profile = ctx.static_profile || {};
      setPreferredName(profile.preferred_name || "");
      setAddress(profile.current_address || "");
      setCaregiverNames((profile.caregiver_names || []).join(", "));
      setMedicalNotes((profile.medical_notes || []).join("\n"));

      // Format triggers: "frase|severidad" per line
      const triggers = ctx.trigger_phrases || [];
      setTriggerPhrases(triggers.map((t) => `${t.text}|${t.severity}`).join("\n"));

      // Format rules: "patrón|riesgo" per line
      const rules = ctx.risk_rules || [];
      setRiskRules(rules.map((r) => `${r.pattern}|${r.risk}`).join("\n"));
    } catch (e) {
      Alert.alert("Error", e.message);
    } finally {
      setLoading(false);
    }
  };

  const sendVoiceSample = useCallback(async (rec) => {
    if (!rec) return;
    try {
      setVoiceStatus("uploading");
      await rec.stopAndUnloadAsync();
      const uri = rec.getURI();
      recordingRef.current = null;
      setRecording(null);
      await uploadVoiceSample(patient.id, uri);
      setVoiceStatus("done");
      Alert.alert("Listo", "Muestra de voz registrada correctamente.");
    } catch (e) {
      setVoiceStatus(null);
      Alert.alert("Error", "Error al subir la muestra: " + e.message);
    }
  }, [patient.id]);

  const startVoiceRecording = async () => {
    try {
      const perm = await Audio.requestPermissionsAsync();
      if (!perm.granted) {
        Alert.alert("Permiso necesario", "Se necesita acceso al micrófono.");
        return;
      }
      await Audio.setAudioModeAsync({ allowsRecordingIOS: true, playsInSilentModeIOS: true });
      const { recording: rec } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY
      );
      recordingRef.current = rec;
      setRecording(rec);
      setVoiceStatus("recording");
      setVoiceProgress(0);
      progressAnim.setValue(0);

      // Animate the bar smoothly to full over VOICE_DURATION_MS
      Animated.timing(progressAnim, {
        toValue: 1,
        duration: VOICE_DURATION_MS,
        useNativeDriver: false,
      }).start();

      // Track progress for the text counter + auto-send at the end
      let elapsed = 0;
      timerRef.current = setInterval(() => {
        elapsed += TICK_MS;
        const pct = Math.min(elapsed / VOICE_DURATION_MS, 1);
        setVoiceProgress(pct);
        if (elapsed >= VOICE_DURATION_MS) {
          clearInterval(timerRef.current);
          timerRef.current = null;
          // Auto-send
          sendVoiceSample(recordingRef.current);
        }
      }, TICK_MS);
    } catch (e) {
      Alert.alert("Error", "No se pudo iniciar la grabación: " + e.message);
    }
  };

  const cancelVoiceRecording = async () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    progressAnim.stopAnimation();
    const rec = recordingRef.current;
    if (rec) {
      try {
        await rec.stopAndUnloadAsync();
      } catch {}
      recordingRef.current = null;
      setRecording(null);
    }
    setVoiceStatus(null);
    setVoiceProgress(0);
  };

  const handleSave = async () => {
    try {
      const newContext = {
        ...context,
        static_profile: {
          preferred_name: preferredName,
          current_address: address,
          caregiver_names: caregiverNames.split(",").map((s) => s.trim()).filter(Boolean),
          medical_notes: medicalNotes.split("\n").filter(Boolean),
        },
        trigger_phrases: triggerPhrases
          .split("\n")
          .filter(Boolean)
          .map((line) => {
            const [text, sev] = line.split("|");
            return { text: text.trim(), severity: parseInt(sev) || 3 };
          }),
        risk_rules: riskRules
          .split("\n")
          .filter(Boolean)
          .map((line) => {
            const [pattern, risk] = line.split("|");
            return { pattern: pattern.trim(), risk: risk?.trim() || "", action: "alert_caregiver" };
          }),
      };

      await updatePatientContext(patient.id, newContext);
      Alert.alert("Guardado", "Contexto actualizado correctamente.");
    } catch (e) {
      Alert.alert("Error", e.message);
    }
  };

  if (loading) {
    return (
      <View style={styles.container}>
        <Text style={styles.loading}>Cargando contexto...</Text>
      </View>
    );
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Pressable onPress={onBack}>
        <Text style={styles.back}>← Volver</Text>
      </Pressable>

      <Text style={styles.title}>Contexto de {patient.full_name}</Text>

      <Text style={styles.label}>Nombre preferido</Text>
      <TextInput style={styles.input} value={preferredName} onChangeText={setPreferredName} />

      <Text style={styles.label}>Dirección actual</Text>
      <TextInput style={styles.input} value={address} onChangeText={setAddress} />

      <Text style={styles.label}>Nombres de cuidadores (separados por coma)</Text>
      <TextInput style={styles.input} value={caregiverNames} onChangeText={setCaregiverNames} />

      <Text style={styles.label}>Notas médicas (una por línea)</Text>
      <TextInput
        style={[styles.input, styles.multiline]}
        value={medicalNotes}
        onChangeText={setMedicalNotes}
        multiline
        numberOfLines={3}
      />

      <Text style={styles.label}>Frases gatillo (frase|severidad, una por línea)</Text>
      <Text style={styles.hint}>Ej: ayuda|5</Text>
      <TextInput
        style={[styles.input, styles.multiline]}
        value={triggerPhrases}
        onChangeText={setTriggerPhrases}
        multiline
        numberOfLines={4}
      />

      <Text style={styles.label}>Reglas de riesgo (patrón regex|riesgo, una por línea)</Text>
      <Text style={styles.hint}>Ej: autobús|bus|tendencia a desorientarse</Text>
      <TextInput
        style={[styles.input, styles.multiline]}
        value={riskRules}
        onChangeText={setRiskRules}
        multiline
        numberOfLines={4}
      />

      <Text style={styles.label}>Muestra de voz del paciente</Text>
      <Text style={styles.hint}>
        Graba 10 segundos del paciente hablando para identificar su voz. Se envía automáticamente al completarse.
      </Text>
      {voiceStatus === "recording" ? (
        <View>
          <View style={styles.progressContainer}>
            <Animated.View
              style={[
                styles.progressBar,
                {
                  width: progressAnim.interpolate({
                    inputRange: [0, 1],
                    outputRange: ["0%", "100%"],
                  }),
                },
              ]}
            />
          </View>
          <Text style={styles.progressText}>
            {Math.round(voiceProgress * 10)}s / 10s
          </Text>
          <Pressable style={[styles.voiceBtn, styles.voiceBtnCancel]} onPress={cancelVoiceRecording}>
            <Text style={styles.voiceBtnText}>✕ Cancelar grabación</Text>
          </Pressable>
        </View>
      ) : voiceStatus === "uploading" ? (
        <View style={[styles.voiceBtn, styles.voiceBtnDisabled]}>
          <Text style={styles.voiceBtnText}>Subiendo muestra...</Text>
        </View>
      ) : (
        <Pressable style={styles.voiceBtn} onPress={startVoiceRecording}>
          <Text style={styles.voiceBtnText}>
            {voiceStatus === "done" ? "🎙 Regrabar muestra de voz" : "🎙 Grabar muestra de voz"}
          </Text>
        </Pressable>
      )}

      <Pressable style={styles.saveBtn} onPress={handleSave}>
        <Text style={styles.saveText}>Guardar contexto</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#F5F7FA" },
  content: { padding: 20, paddingTop: 50 },
  loading: { marginTop: 100, textAlign: "center", fontSize: 16, color: "#999" },
  back: { color: "#4A90D9", fontSize: 16, marginBottom: 16 },
  title: { fontSize: 22, fontWeight: "700", marginBottom: 20 },
  label: { fontSize: 14, fontWeight: "600", color: "#333", marginTop: 14, marginBottom: 4 },
  hint: { fontSize: 12, color: "#999", marginBottom: 4 },
  input: {
    backgroundColor: "#fff",
    borderRadius: 10,
    padding: 12,
    fontSize: 15,
    borderWidth: 1,
    borderColor: "#E0E0E0",
  },
  multiline: { minHeight: 80, textAlignVertical: "top" },
  saveBtn: {
    backgroundColor: "#4A90D9",
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: "center",
    marginTop: 24,
    marginBottom: 40,
  },
  saveText: { color: "#fff", fontSize: 17, fontWeight: "700" },
  voiceBtn: {
    backgroundColor: "#27AE60",
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 8,
  },
  voiceBtnCancel: { backgroundColor: "#E74C3C" },
  voiceBtnDisabled: { backgroundColor: "#999" },
  voiceBtnText: { color: "#fff", fontSize: 15, fontWeight: "600" },
  progressContainer: {
    height: 20,
    backgroundColor: "#E0E0E0",
    borderRadius: 10,
    marginTop: 10,
    overflow: "hidden",
  },
  progressBar: {
    height: "100%",
    backgroundColor: "#27AE60",
    borderRadius: 10,
  },
  progressText: {
    textAlign: "center",
    marginTop: 6,
    fontSize: 14,
    fontWeight: "600",
    color: "#333",
  },
});
