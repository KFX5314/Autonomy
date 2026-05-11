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
import appConfig from "../config/appConfig";
import { getPatientContext, updatePatientContext, uploadVoiceSample } from "../services/api";
import PhraseListEditor from "../components/PhraseListEditor";

const { voiceSample } = appConfig;
const voiceSampleSeconds = Math.round(voiceSample.durationMs / 1000);

export default function PatientContextScreen({ patient, onBack }) {
  const [context, setContext] = useState(null);
  const [loading, setLoading] = useState(true);

  // Editable fields
  const [preferredName, setPreferredName] = useState("");
  const [address, setAddress] = useState("");
  const [caregiverNames, setCaregiverNames] = useState("");
  const [medicalNotes, setMedicalNotes] = useState("");
  const [episodeWatchInstructions, setEpisodeWatchInstructions] = useState("");
  const [alertPhrases, setAlertPhrases] = useState([]);      // [{text, severity, regex}]
  const [wakeWords, setWakeWords] = useState([]);            // [{text}]
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [recording, setRecording] = useState(null);
  const [voiceStatus, setVoiceStatus] = useState(null); // null | "recording" | "uploading" | "done"
  const [voiceProgress, setVoiceProgress] = useState(0); // 0-1
  const progressAnim = useRef(new Animated.Value(0)).current;
  const timerRef = useRef(null);
  const recordingRef = useRef(null);

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
      setEpisodeWatchInstructions(ctx.episode_watch_instructions || "");

      // Load unified alert_phrases (merging legacy trigger_phrases + risk_rules
      // if the backend still has those).
      let phrases = [];
      if (Array.isArray(ctx.alert_phrases) && ctx.alert_phrases.length) {
        phrases = ctx.alert_phrases.map((it) =>
          typeof it === "string"
            ? { text: it, severity: 3, regex: false }
            : {
                text: it.text || "",
                severity: Number(it.severity) || 3,
                regex: !!it.regex,
              }
        );
      } else {
        for (const t of ctx.trigger_phrases || []) {
          if (typeof t === "string") phrases.push({ text: t, severity: 3, regex: false });
          else if (t && t.text)
            phrases.push({
              text: t.text,
              severity: Number(t.severity) || 3,
              regex: !!t.regex,
            });
        }
        for (const r of ctx.risk_rules || []) {
          const pat = typeof r === "string" ? r : r.pattern || r.text;
          if (pat)
            phrases.push({
              text: pat,
              severity: Number(r.severity) || 4,
              regex: r.regex !== undefined ? !!r.regex : true,
            });
        }
      }
      setAlertPhrases(phrases);

      const waw = (ctx.assistant_wake_words || []).map((w) =>
        typeof w === "string" ? { text: w } : { text: w?.text || "" }
      );
      setWakeWords(waw);
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

      // Animate the bar smoothly to full over the configured sample duration.
      Animated.timing(progressAnim, {
        toValue: 1,
        duration: voiceSample.durationMs,
        useNativeDriver: false,
      }).start();

      // Track progress for the text counter + auto-send at the end
      let elapsed = 0;
      timerRef.current = setInterval(() => {
        elapsed += voiceSample.tickMs;
        const pct = Math.min(elapsed / voiceSample.durationMs, 1);
        setVoiceProgress(pct);
        if (elapsed >= voiceSample.durationMs) {
          clearInterval(timerRef.current);
          timerRef.current = null;
          // Auto-send
          sendVoiceSample(recordingRef.current);
        }
      }, voiceSample.tickMs);
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
      const cleanedPhrases = alertPhrases
        .map((p) => ({
          text: (p.text || "").trim(),
          severity: Math.max(1, Math.min(5, Number(p.severity) || 3)),
          regex: !!p.regex,
        }))
        .filter((p) => p.text);

      const cleanedWakeWords = wakeWords
        .map((w) => (w.text || "").trim().toLowerCase())
        .filter(Boolean);

      const newContext = {
        ...context,
        static_profile: {
          preferred_name: preferredName,
          current_address: address,
          caregiver_names: caregiverNames.split(",").map((s) => s.trim()).filter(Boolean),
          medical_notes: medicalNotes.split("\n").filter(Boolean),
        },
        episode_watch_instructions: episodeWatchInstructions.trim(),
        alert_phrases: cleanedPhrases,
        assistant_wake_words: cleanedWakeWords,
      };
      // Drop the legacy keys so the server stores the canonical shape.
      delete newContext.trigger_phrases;
      delete newContext.risk_rules;

      await updatePatientContext(patient.id, newContext);
      Alert.alert("Guardado", "Contexto actualizado correctamente.");
      if (onBack) onBack();
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

      <Text style={styles.label}>Qué debe vigilar el asistente</Text>
      <Text style={styles.hint}>
        Describe en lenguaje natural situaciones, comportamientos o temas que
        puedan indicar un episodio para este paciente.
      </Text>
      <TextInput
        style={[styles.input, styles.watchInput]}
        value={episodeWatchInstructions}
        onChangeText={setEpisodeWatchInstructions}
        placeholder="Ej. Si habla de ir a su antiguo trabajo, puede estar desorientado."
        multiline
        numberOfLines={5}
      />

      <Pressable style={styles.advancedHeader} onPress={() => setAdvancedOpen((v) => !v)}>
        <Text style={styles.advancedTitle}>Avanzado</Text>
        <Text style={styles.advancedIcon}>{advancedOpen ? "v" : ">"}</Text>
      </Pressable>
      {advancedOpen ? (
        <View style={styles.advancedBody}>
          <Text style={styles.label}>Frases de alerta y patrones técnicos</Text>
          <Text style={styles.hint}>
            Estas frases o regex se comprueban antes del LLM. Úsalas para casos
            técnicos concretos. "Ayuda" se mantiene siempre como palabra de emergencia.
          </Text>
          <PhraseListEditor
            value={alertPhrases}
            onChange={setAlertPhrases}
            mode="alert"
            addLabel="Añadir frase de alerta"
          />
        </View>
      ) : null}

      <Text style={styles.label}>Palabras de activación del asistente</Text>
      <Text style={styles.hint}>
        Cuando el paciente diga una de estas palabras (p. ej. "asistente",
        "ayúdame"), el sistema responderá con voz en vez de generar alerta.
      </Text>
      <PhraseListEditor
        value={wakeWords}
        onChange={setWakeWords}
        mode="wake"
        addLabel="Añadir palabra de activación"
      />

      <Text style={styles.label}>Muestra de voz del paciente</Text>
      <Text style={styles.hint}>
        Graba {voiceSampleSeconds} segundos del paciente hablando para identificar su voz. Se envía automáticamente al
        completarse.
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
            {Math.round(voiceProgress * voiceSampleSeconds)}s / {voiceSampleSeconds}s
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
  watchInput: { minHeight: 120, textAlignVertical: "top" },
  advancedHeader: {
    marginTop: 18,
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#D8E6F5",
    backgroundColor: "#EEF6FF",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  advancedTitle: { color: "#2F6EA8", fontSize: 15, fontWeight: "700" },
  advancedIcon: { color: "#2F6EA8", fontSize: 18, fontWeight: "700" },
  advancedBody: {
    borderWidth: 1,
    borderTopWidth: 0,
    borderColor: "#D8E6F5",
    borderBottomLeftRadius: 10,
    borderBottomRightRadius: 10,
    padding: 12,
    backgroundColor: "#FAFCFF",
  },
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
