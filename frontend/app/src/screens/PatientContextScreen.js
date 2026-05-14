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
  Switch,
} from "react-native";
import { Audio } from "expo-av";
import appConfig from "../config/appConfig";
import {
  deleteVoiceSample,
  getPatientContext,
  getVoiceSamples,
  updatePatientContext,
  uploadVoiceSample,
} from "../services/api";
import PhraseListEditor from "../components/PhraseListEditor";

const { voiceSample } = appConfig;
const voiceSampleSeconds = Math.round(voiceSample.durationMs / 1000);
const COLOR_OPTIONS = ["#4A90D9", "#27AE60", "#E67E22", "#9B59B6", "#E74C3C", "#16A085"];

export default function PatientContextScreen({ patient, onBack }) {
  const [context, setContext] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [preferredName, setPreferredName] = useState("");
  const [address, setAddress] = useState("");
  const [caregiverNames, setCaregiverNames] = useState("");
  const [medicalNotes, setMedicalNotes] = useState("");
  const [episodeWatchInstructions, setEpisodeWatchInstructions] = useState("");
  const [uiColor, setUiColor] = useState("#4A90D9");
  const [ttsEnabled, setTtsEnabled] = useState(true);
  const [alertPhrases, setAlertPhrases] = useState([]);      // [{text, severity, regex}]
  const [wakeWords, setWakeWords] = useState([]);            // [{text}]
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [voiceSamples, setVoiceSamples] = useState([]);
  const [voiceManagerOpen, setVoiceManagerOpen] = useState(false);
  const [recording, setRecording] = useState(null);
  const [voiceStatus, setVoiceStatus] = useState(null); // null | "recording" | "uploading" | "done"
  const [voiceProgress, setVoiceProgress] = useState(0); // 0-1
  const progressAnim = useRef(new Animated.Value(0)).current;
  const timerRef = useRef(null);
  const recordingRef = useRef(null);
  const savingRef = useRef(false);

  useEffect(() => {
    loadContext();
  }, []);

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
      setUiColor(ctx.ui_color || "#4A90D9");
      setTtsEnabled(ctx.tts_enabled !== false);

      // Old saved contexts may still store trigger_phrases + risk_rules.
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

      const voice = await getVoiceSamples(patient.id);
      setVoiceSamples(voice.samples || []);
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
      const result = await uploadVoiceSample(patient.id, uri);
      if (result?.samples) setVoiceSamples(result.samples);
      setVoiceStatus("done");
      Alert.alert("Listo", `Muestra de voz registrada correctamente (${result?.count || 1}/10).`);
    } catch (e) {
      setVoiceStatus(null);
      Alert.alert("Error", "Error al subir la muestra: " + e.message);
    }
  }, [patient.id]);

  const handleDeleteVoiceSample = async (sampleId) => {
    try {
      const result = await deleteVoiceSample(patient.id, sampleId);
      setVoiceSamples(result.samples || []);
    } catch (e) {
      Alert.alert("Error", "No se pudo borrar la muestra: " + e.message);
    }
  };

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

      let elapsed = 0;
      timerRef.current = setInterval(() => {
        elapsed += voiceSample.tickMs;
        const pct = Math.min(elapsed / voiceSample.durationMs, 1);
        setVoiceProgress(pct);
        if (elapsed >= voiceSample.durationMs) {
          clearInterval(timerRef.current);
          timerRef.current = null;
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
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(true);

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
        ui_color: uiColor,
        tts_enabled: !!ttsEnabled,
        alert_phrases: cleanedPhrases,
        assistant_wake_words: cleanedWakeWords,
      };
      // Store only the unified alert_phrases shape after editing.
      delete newContext.trigger_phrases;
      delete newContext.risk_rules;

      await updatePatientContext(patient.id, newContext);
      Alert.alert("Guardado", "Contexto actualizado correctamente.", [
        { text: "OK", onPress: () => onBack?.() },
      ]);
    } catch (e) {
      savingRef.current = false;
      setSaving(false);
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

      <Text style={styles.title}>Configuración de {patient.full_name}</Text>

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

      <Text style={styles.label}>Color del paciente</Text>
      <View style={styles.colorRow}>
        {COLOR_OPTIONS.map((color) => (
          <Pressable
            key={color}
            style={[
              styles.colorSwatch,
              { backgroundColor: color },
              uiColor === color && styles.colorSwatchActive,
            ]}
            onPress={() => setUiColor(color)}
          />
        ))}
      </View>

      <View style={styles.switchRow}>
        <View style={styles.switchText}>
          <Text style={styles.label}>TTS por defecto</Text>
          <Text style={styles.hint}>
            Si está apagado, el paciente seguirá enviando audio y alertas, pero no escuchará respuestas.
          </Text>
        </View>
        <Switch value={ttsEnabled} onValueChange={setTtsEnabled} />
      </View>

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
        Graba {voiceSampleSeconds} segundos del paciente hablando. Puedes guardar hasta 10 muestras para mejorar la
        identificación.
      </Text>
      <View style={styles.voiceHeaderRow}>
        <Text style={styles.voiceCount}>{voiceSamples.length}/10 muestras guardadas</Text>
        <Pressable style={styles.manageVoiceBtn} onPress={() => setVoiceManagerOpen((v) => !v)}>
          <Text style={styles.manageVoiceIcon}>✎</Text>
          <Text style={styles.manageVoiceText}>Editar</Text>
        </Pressable>
      </View>
      {voiceManagerOpen ? (
        <View style={styles.voiceManager}>
          {voiceSamples.length ? (
            voiceSamples.map((sample, index) => (
              <View key={sample.id} style={styles.voiceSampleRow}>
                <View>
                  <Text style={styles.voiceSampleTitle}>Muestra {index + 1}</Text>
                  <Text style={styles.voiceSampleMeta}>
                    {sample.created_at ? new Date(sample.created_at).toLocaleString("es-ES") : "Muestra antigua"}
                  </Text>
                </View>
                <Pressable
                  style={styles.voiceDeleteBtn}
                  onPress={() =>
                    Alert.alert("Borrar muestra", "¿Quieres eliminar esta muestra de voz?", [
                      { text: "Cancelar", style: "cancel" },
                      { text: "Borrar", style: "destructive", onPress: () => handleDeleteVoiceSample(sample.id) },
                    ])
                  }
                >
                  <Text style={styles.voiceDeleteText}>Borrar</Text>
                </Pressable>
              </View>
            ))
          ) : (
            <Text style={styles.hint}>Todavía no hay muestras guardadas.</Text>
          )}
        </View>
      ) : null}
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

      <Pressable
        style={[styles.saveBtn, saving && styles.saveBtnDisabled]}
        onPress={handleSave}
        disabled={saving}
      >
        <Text style={styles.saveText}>{saving ? "Guardando..." : "Guardar configuración"}</Text>
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
  colorRow: { flexDirection: "row", gap: 10, marginBottom: 8 },
  colorSwatch: {
    width: 34,
    height: 34,
    borderRadius: 17,
    borderWidth: 2,
    borderColor: "transparent",
  },
  colorSwatchActive: { borderColor: "#222" },
  switchRow: {
    marginTop: 12,
    padding: 12,
    borderRadius: 10,
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#E0E0E0",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  switchText: { flex: 1, paddingRight: 12 },
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
  voiceHeaderRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 8,
    marginBottom: 8,
  },
  voiceCount: { color: "#555", fontSize: 13, fontWeight: "600" },
  manageVoiceBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#4A90D9",
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  manageVoiceIcon: { color: "#4A90D9", fontSize: 15, fontWeight: "700" },
  manageVoiceText: { color: "#4A90D9", fontSize: 13, fontWeight: "700" },
  voiceManager: {
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#E0E0E0",
    backgroundColor: "#fff",
    padding: 10,
    marginBottom: 10,
  },
  voiceSampleRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: "#F1F1F1",
  },
  voiceSampleTitle: { fontSize: 14, fontWeight: "700", color: "#333" },
  voiceSampleMeta: { fontSize: 12, color: "#777", marginTop: 2 },
  voiceDeleteBtn: {
    borderRadius: 8,
    backgroundColor: "#FDECEC",
    paddingHorizontal: 10,
    paddingVertical: 7,
  },
  voiceDeleteText: { color: "#E74C3C", fontSize: 12, fontWeight: "700" },
  saveBtn: {
    backgroundColor: "#4A90D9",
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: "center",
    marginTop: 24,
    marginBottom: 40,
  },
  saveBtnDisabled: { backgroundColor: "#8DBBE6" },
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
