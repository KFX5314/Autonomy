/**
 * Role-neutral Settings screen.
 *
 * Shows current account info, patient TTS settings, app version,
 * and a prominent red "Cerrar sesión" action. Animated entry: fade + slide up.
 */
import React, { useEffect, useRef, useState } from "react";
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  ScrollView,
  Animated,
  Alert as RNAlert,
  Switch,
} from "react-native";
import Constants from "expo-constants";
import { getMyPatientSettings, sendPatientLogoutWarning } from "../services/api";
import { loadPatientTtsEnabled, savePatientTtsEnabled } from "../services/session";

export default function SettingsScreen({ navigation, route, user: propUser, onLogout: propOnLogout }) {
  const user = propUser || route?.params?.user;
  const onLogout = propOnLogout || route?.params?.onLogout;
  const isPatient = user?.role === "patient";
  const userId = user?.user_id || user?.id;
  const [caregiverTtsEnabled, setCaregiverTtsEnabled] = useState(true);
  const [localTtsEnabled, setLocalTtsEnabled] = useState(true);

  const fade = useRef(new Animated.Value(0)).current;
  const translate = useRef(new Animated.Value(16)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.timing(fade, { toValue: 1, duration: 250, useNativeDriver: true }),
      Animated.timing(translate, { toValue: 0, duration: 250, useNativeDriver: true }),
    ]).start();
  }, [fade, translate]);

  useEffect(() => {
    if (!isPatient) return;
    (async () => {
      const localEnabled = await loadPatientTtsEnabled(userId);
      setLocalTtsEnabled(localEnabled);
      try {
        const settings = await getMyPatientSettings();
        setCaregiverTtsEnabled(settings.tts_enabled !== false);
      } catch (e) {
        console.warn("Could not load patient settings:", e?.message || e);
      }
    })();
  }, [isPatient, userId]);

  const version =
    Constants?.expoConfig?.version ||
    Constants?.manifest?.version ||
    "0.1.0";

  const effectiveTtsEnabled = caregiverTtsEnabled && localTtsEnabled;
  const canGoBack = navigation?.canGoBack?.() ?? false;
  const backLabel = isPatient ? "Inicio" : "Mis pacientes";

  const handleTtsToggle = async (value) => {
    setLocalTtsEnabled(value);
    await savePatientTtsEnabled(userId, value);
  };

  const performLogout = async () => {
    if (isPatient) {
      try {
        await sendPatientLogoutWarning();
      } catch (e) {
        console.warn("Could not notify caregiver about patient logout:", e?.message || e);
      }
    }
    if (onLogout) await onLogout();
  };

  const handleLogout = () => {
    if (!isPatient) {
      performLogout();
      return;
    }
    RNAlert.alert(
      "Cerrar sesión",
      "Si cierras sesión, tu cuidador recibirá un aviso. ¿Quieres continuar?",
      [
        { text: "Cancelar", style: "cancel" },
        { text: "Cerrar sesión", style: "destructive", onPress: performLogout },
      ]
    );
  };

  return (
    <Animated.View style={[styles.wrap, { opacity: fade, transform: [{ translateY: translate }] }]}>
      <ScrollView contentContainerStyle={styles.content}>
        {canGoBack ? (
          <Pressable
            style={({ pressed }) => [styles.backBtn, pressed && styles.backBtnPressed]}
            onPress={() => navigation.goBack()}
            hitSlop={8}
          >
            <Text style={styles.backIcon}>←</Text>
            <Text style={styles.backText}>{backLabel}</Text>
          </Pressable>
        ) : null}
        <Text style={styles.title}>Ajustes</Text>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Cuenta</Text>
          {user?.username ? (
            <View style={styles.row}>
              <Text style={styles.rowLabel}>Usuario</Text>
              <Text style={styles.rowValue}>{user.username}</Text>
            </View>
          ) : null}
          {user?.email ? (
            <View style={styles.row}>
              <Text style={styles.rowLabel}>Correo</Text>
              <Text style={styles.rowValue}>{user.email}</Text>
            </View>
          ) : null}
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Rol</Text>
            <Text style={styles.rowValue}>
              {user?.role === "caregiver" ? "Cuidador" : user?.role === "patient" ? "Paciente" : "—"}
            </Text>
          </View>
        </View>

        {isPatient ? (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Preferencias</Text>
            <View style={styles.item}>
              <View style={styles.itemTextBlock}>
                <Text style={styles.itemLabel}>TTS del paciente</Text>
                <Text style={styles.itemHint}>
                  {caregiverTtsEnabled
                    ? "Reproduce respuestas por voz en este dispositivo."
                    : "Desactivado por el responsable."}
                </Text>
              </View>
              <Switch
                value={effectiveTtsEnabled}
                disabled={!caregiverTtsEnabled}
                onValueChange={handleTtsToggle}
              />
            </View>
          </View>
        ) : null}

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Acerca de</Text>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Versión</Text>
            <Text style={styles.rowValue}>{version}</Text>
          </View>
        </View>

        <Pressable
          style={({ pressed }) => [styles.logoutBtn, pressed && styles.logoutBtnPressed]}
          onPress={handleLogout}
        >
          <Text style={styles.logoutText}>Cerrar sesión</Text>
        </Pressable>
      </ScrollView>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#F5F7FA" },
  content: { padding: 20, paddingTop: 24, paddingBottom: 60 },
  backBtn: {
    alignSelf: "flex-start",
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 7,
    marginBottom: 12,
  },
  backBtnPressed: { backgroundColor: "#DCEAF8" },
  backIcon: { color: "#4A90D9", fontSize: 18, fontWeight: "800" },
  backText: { color: "#4A90D9", fontSize: 15, fontWeight: "700" },
  title: { fontSize: 26, fontWeight: "700", marginBottom: 20 },
  section: {
    backgroundColor: "#fff",
    borderRadius: 14,
    padding: 4,
    marginBottom: 18,
    borderWidth: 1,
    borderColor: "#E6E6E6",
  },
  sectionTitle: {
    fontSize: 13,
    color: "#888",
    textTransform: "uppercase",
    fontWeight: "700",
    paddingHorizontal: 12,
    paddingTop: 10,
    paddingBottom: 6,
    letterSpacing: 0.5,
  },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingHorizontal: 12,
    paddingVertical: 12,
    borderTopWidth: 1,
    borderTopColor: "#F1F1F1",
  },
  rowLabel: { fontSize: 15, color: "#444" },
  rowValue: { fontSize: 15, color: "#222", fontWeight: "500" },
  item: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: 12,
    paddingVertical: 14,
    borderTopWidth: 1,
    borderTopColor: "#F1F1F1",
  },
  itemTextBlock: { flex: 1, paddingRight: 12 },
  itemLabel: { fontSize: 15, color: "#222" },
  itemHint: { fontSize: 12, color: "#777", marginTop: 3 },
  logoutBtn: {
    backgroundColor: "#E74C3C",
    borderRadius: 14,
    paddingVertical: 16,
    alignItems: "center",
    marginTop: 10,
  },
  logoutBtnPressed: { backgroundColor: "#C94032" },
  logoutText: { color: "#fff", fontSize: 17, fontWeight: "700" },
});
