/**
 * Caregiver Home - patient list, alerts overview.
 */
import React, { useState, useCallback } from "react";
import {
  View,
  Text,
  Pressable,
  FlatList,
  StyleSheet,
  Alert,
  RefreshControl,
  Platform,
  AppState,
} from "react-native";
import * as Notifications from "expo-notifications";
import { useFocusEffect } from "@react-navigation/native";
import appConfig from "../config/appConfig";
import {
  getPatients,
  getPatientContext,
  getAlerts,
  ackAlert,
  getPatientJournal,
  getPatientShortTermMemory,
  registerPushToken,
} from "../services/api";
import AlertCard from "../components/AlertCard";

const { caregiver } = appConfig;

async function registerCaregiverPushToken() {
  if (Platform.OS === "web") return null;

  const existing = await Notifications.getPermissionsAsync();
  let status = existing.status;
  if (status !== "granted") {
    const requested = await Notifications.requestPermissionsAsync();
    status = requested.status;
  }
  if (status !== "granted") return null;

  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("alerts", {
      name: "Alertas",
      importance: Notifications.AndroidImportance.MAX,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: "#E74C3C",
    });
  }

  const token = (await Notifications.getExpoPushTokenAsync()).data;
  return token || null;
}

function PatientActionButton({ icon, label, onPress, color }) {
  return (
    <Pressable
      style={({ pressed }) => [
        styles.patientActionBtn,
        { borderColor: color },
        pressed && styles.patientActionBtnPressed,
      ]}
      onPress={onPress}
    >
      {icon === "live" ? (
        <LiveSignalIcon color={color} />
      ) : (
        <Text style={[styles.patientActionIcon, { color }]}>{icon}</Text>
      )}
      <Text style={styles.patientActionLabel}>{label}</Text>
    </Pressable>
  );
}

function LiveSignalIcon({ color }) {
  return (
    <View style={styles.liveSignalIcon}>
      <View style={[styles.liveSignalDot, { backgroundColor: color }]} />
      <View style={[styles.liveSignalBar, { height: 8, backgroundColor: color }]} />
      <View style={[styles.liveSignalBar, { height: 14, backgroundColor: color }]} />
      <View style={[styles.liveSignalBar, { height: 10, backgroundColor: color }]} />
    </View>
  );
}

function CloseButton({ onPress }) {
  return (
    <Pressable
      style={({ pressed }) => [styles.closeBtn, pressed && styles.closeBtnPressed]}
      onPress={onPress}
    >
      <Text style={styles.closeIcon}>×</Text>
      <Text style={styles.closeLabel}>Cerrar</Text>
    </Pressable>
  );
}

export default function CaregiverHomeScreen({ user, onLogout, onEditContext, onOpenSettings }) {
  const [patients, setPatients] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [detailPatient, setDetailPatient] = useState(null); // {id, name} or null
  const [detailTab, setDetailTab] = useState("journal"); // "journal" | "advanced"
  const [journalEntries, setJournalEntries] = useState([]);
  const [journalLoading, setJournalLoading] = useState(false);
  const [shortTermMemory, setShortTermMemory] = useState(null);
  const [stmLoading, setStmLoading] = useState(false);

  React.useEffect(() => {
    let cancelled = false;
    if (user?.role !== "caregiver") return undefined;

    (async () => {
      try {
        const token = await registerCaregiverPushToken();
        if (!token || cancelled) return;
        await registerPushToken({
          token,
          platform: Platform.OS,
          deviceId: String(user?.user_id || user?.id || ""),
        });
      } catch (e) {
        console.warn("Could not register push token:", e?.message || e);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [user?.id, user?.role, user?.user_id]);

  const refresh = useCallback(async ({ silent = false, showSpinner = true } = {}) => {
    if (showSpinner) setRefreshing(true);
    try {
      const [p, a] = await Promise.all([getPatients(), getAlerts()]);
      const enrichedPatients = await Promise.all(
        p.map(async (patient) => {
          try {
            const context = await getPatientContext(patient.id);
            return {
              ...patient,
              ui_color: context.context_json?.ui_color || "#4A90D9",
            };
          } catch {
            return { ...patient, ui_color: "#4A90D9" };
          }
        })
      );
      setPatients(enrichedPatients);
      setAlerts(a);
      setLoaded(true);
    } catch (e) {
      if (!silent) Alert.alert("Error", e.message);
    } finally {
      if (showSpinner) setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      refresh({ silent: true, showSpinner: !loaded });
      const refreshMs = Math.max(1000, caregiver.alertRefreshMs);
      const interval = setInterval(() => {
        refresh({ silent: true, showSpinner: false });
      }, refreshMs);

      return () => clearInterval(interval);
    }, [loaded, refresh])
  );

  const handleAck = async (alertId) => {
    try {
      await ackAlert(alertId);
      refresh({ showSpinner: false });
    } catch (e) {
      Alert.alert("Error", e.message);
    }
  };

  const loadJournal = useCallback(async (patientId, { silent = false } = {}) => {
    setJournalLoading(true);
    try {
      const entries = await getPatientJournal(patientId, 24, 100);
      setJournalEntries(entries);
    } catch (e) {
      if (!silent) Alert.alert("Error", e.message);
    } finally {
      setJournalLoading(false);
    }
  }, []);

  const loadShortTermMemory = useCallback(async (patientId, { silent = false, showSpinner = true } = {}) => {
    if (showSpinner) setStmLoading(true);
    try {
      const data = await getPatientShortTermMemory(patientId);
      setShortTermMemory(data);
    } catch (e) {
      if (!silent) Alert.alert("Error", e.message);
    } finally {
      if (showSpinner) setStmLoading(false);
    }
  }, []);

  React.useEffect(() => {
    if (!detailPatient) return;
    if (detailTab === "journal") {
      loadJournal(detailPatient.id);
    } else {
      loadShortTermMemory(detailPatient.id);
    }
  }, [detailPatient, detailTab, loadJournal, loadShortTermMemory]);

  useFocusEffect(
    useCallback(() => {
      if (!detailPatient || detailTab !== "advanced") return undefined;
      const refreshMs = Math.max(1000, caregiver.liveRefreshMs);
      let interval = null;

      const stop = () => {
        if (interval) {
          clearInterval(interval);
          interval = null;
        }
      };
      const start = () => {
        if (interval) return;
        interval = setInterval(() => {
          loadShortTermMemory(detailPatient.id, { silent: true, showSpinner: false });
        }, refreshMs);
      };

      if (AppState.currentState === "active") start();
      const subscription = AppState.addEventListener("change", (state) => {
        if (state === "active") {
          start();
        } else {
          stop();
        }
      });

      return () => {
        stop();
        subscription.remove();
      };
    }, [detailPatient, detailTab, loadShortTermMemory])
  );

  const openPatientDetail = useCallback((patient, tab) => {
    setShowHistory(false);
    setJournalEntries([]);
    setShortTermMemory(null);
    setDetailPatient({ id: patient.id, name: patient.full_name });
    setDetailTab(tab);
  }, []);

  const closePatientDetail = useCallback(() => {
    setDetailPatient(null);
    setJournalEntries([]);
    setShortTermMemory(null);
  }, []);

  const refreshDetail = useCallback(() => {
    if (!detailPatient) return undefined;
    if (detailTab === "journal") {
      return loadJournal(detailPatient.id);
    }
    return loadShortTermMemory(detailPatient.id);
  }, [detailPatient, detailTab, loadJournal, loadShortTermMemory]);

  const patientName = (patientId) => {
    const p = patients.find((p) => p.id === patientId);
    return p ? p.full_name : `Paciente #${patientId}`;
  };

  const newAlerts = alerts.filter((a) => a.status === "NEW");
  const pastAlerts = alerts.filter((a) => a.status !== "NEW");
  const stmRows = shortTermMemory?.memory ? [shortTermMemory] : [];

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.greeting}>Hola, {user.full_name}</Text>
        <Pressable onPress={onOpenSettings} hitSlop={10} style={styles.gearBtn}>
          <Text style={styles.gear}>⚙︎</Text>
        </Pressable>
      </View>

      <Text style={styles.sectionTitle}>Mis pacientes</Text>
      {patients.length === 0 && loaded ? (
        <Text style={styles.empty}>No hay pacientes vinculados aun.</Text>
      ) : (
        <FlatList
          data={patients}
          keyExtractor={(item) => String(item.id)}
          horizontal
          showsHorizontalScrollIndicator={false}
          style={styles.patientList}
          renderItem={({ item }) => (
            <View style={[styles.patientCard, { borderLeftColor: item.ui_color || "#4A90D9" }]}>
              <Text style={styles.patientName}>{item.full_name}</Text>
              {item.username ? <Text style={styles.patientUsername}>@{item.username}</Text> : null}
              <View style={styles.patientActions}>
                <PatientActionButton
                  icon="⚙"
                  label="Configuración"
                  color={item.ui_color || "#4A90D9"}
                  onPress={() => onEditContext(item)}
                />
                <PatientActionButton
                  icon="▤"
                  label="Diario"
                  color={item.ui_color || "#4A90D9"}
                  onPress={() => openPatientDetail(item, "journal")}
                />
                <PatientActionButton
                  icon="live"
                  label="En directo"
                  color={item.ui_color || "#4A90D9"}
                  onPress={() => openPatientDetail(item, "advanced")}
                />
              </View>
            </View>
          )}
        />
      )}

      {detailPatient ? (
        <View style={styles.detailPanel}>
          <View style={styles.sectionRow}>
            <Text style={styles.sectionTitle}>{detailPatient.name}</Text>
            <CloseButton onPress={closePatientDetail} />
          </View>

          <View style={styles.tabRow}>
            <Pressable
              style={({ pressed }) => [
                styles.tabBtn,
                detailTab === "journal" && styles.tabBtnActive,
                pressed && styles.tabBtnPressed,
              ]}
              onPress={() => setDetailTab("journal")}
            >
              <Text style={[styles.tabText, detailTab === "journal" && styles.tabTextActive]}>
                Diario
              </Text>
            </Pressable>
            <Pressable
              style={({ pressed }) => [
                styles.tabBtn,
                detailTab === "advanced" && styles.tabBtnActive,
                pressed && styles.tabBtnPressed,
              ]}
              onPress={() => setDetailTab("advanced")}
            >
              <Text style={[styles.tabText, detailTab === "advanced" && styles.tabTextActive]}>
                En directo
              </Text>
            </Pressable>
          </View>

          {detailTab === "journal" ? (
            <FlatList
              data={journalEntries}
              keyExtractor={(item) => String(item.id)}
              refreshControl={<RefreshControl refreshing={journalLoading} onRefresh={refreshDetail} />}
              style={styles.alertList}
              ListEmptyComponent={
                journalLoading ? null : <Text style={styles.empty}>Sin entradas aun. El asistente escribira una cada pocos minutos.</Text>
              }
              renderItem={({ item }) => (
                <View style={styles.alertCard}>
                  <Text style={styles.alertTime}>
                    {new Date(item.created_at).toLocaleString("es-ES")}
                  </Text>
                  <Text style={styles.alertReason}>{item.summary_text}</Text>
                </View>
              )}
            />
          ) : (
            <FlatList
              data={stmRows}
              keyExtractor={(item) => String(item.patient_id)}
              refreshControl={<RefreshControl refreshing={stmLoading} onRefresh={refreshDetail} />}
              style={styles.alertList}
              ListEmptyComponent={
                stmLoading ? null : <Text style={styles.empty}>Sin memoria a corto plazo reciente.</Text>
              }
              renderItem={({ item }) => (
                <View style={styles.alertCard}>
                  <Text style={styles.alertTime}>
                    Ultimos {item.window_minutes} min - max. {item.max_utterances} frases
                  </Text>
                  <Text style={styles.memoryText}>{item.memory}</Text>
                  <Text style={styles.memoryMeta}>
                    Actualizado: {new Date(item.generated_at).toLocaleString("es-ES")}
                  </Text>
                </View>
              )}
            />
          )}
        </View>
      ) : showHistory ? (
        <>
          <View style={styles.sectionRow}>
            <Text style={styles.sectionTitle}>Historial de alertas</Text>
            <Pressable
              style={({ pressed }) => [styles.historyBtn, pressed && styles.historyBtnPressed]}
              onPress={() => setShowHistory(false)}
            >
              <Text style={styles.historyLabel}>Alertas</Text>
            </Pressable>
          </View>
          <FlatList
            data={pastAlerts}
            keyExtractor={(item) => String(item.id)}
            refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} />}
            style={styles.alertList}
            ListEmptyComponent={
              loaded ? <Text style={styles.empty}>Sin alertas pasadas.</Text> : null
            }
            renderItem={({ item }) => (
              <AlertCard
                alert={item}
                patientName={patientName(item.patient_id)}
                isNew={false}
              />
            )}
          />
        </>
      ) : (
        <>
          <View style={styles.sectionRow}>
            <Text style={styles.sectionTitle}>
              Alertas {newAlerts.length > 0 && `(${newAlerts.length} nuevas)`}
            </Text>
            <Pressable
              style={({ pressed }) => [styles.historyBtn, pressed && styles.historyBtnPressed]}
              onPress={() => setShowHistory(true)}
            >
              <Text style={styles.historyLabel}>Historial</Text>
            </Pressable>
          </View>
          <FlatList
            data={newAlerts}
            keyExtractor={(item) => String(item.id)}
            refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} />}
            style={styles.alertList}
            ListEmptyComponent={
              loaded ? <Text style={styles.empty}>Sin alertas nuevas.</Text> : null
            }
            renderItem={({ item }) => (
              <AlertCard
                alert={item}
                patientName={patientName(item.patient_id)}
                isNew={true}
                onAck={handleAck}
              />
            )}
          />
        </>
      )}
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
    marginBottom: 12,
  },
  greeting: { fontSize: 22, fontWeight: "700", flex: 1 },
  gearBtn: { paddingHorizontal: 6, paddingVertical: 4 },
  gear: { fontSize: 24, color: "#555" },
  historyBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  historyBtnPressed: { backgroundColor: "#DCEAF8" },
  historyLabel: { color: "#4A90D9", fontSize: 14, fontWeight: "600" },
  sectionRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 16, marginBottom: 10 },
  sectionTitle: { fontSize: 18, fontWeight: "700" },
  empty: { color: "#999", marginBottom: 10 },
  detailPanel: {
    flex: 1,
    backgroundColor: "#EEF4FA",
    borderRadius: 16,
    borderWidth: 1,
    borderColor: "#D9E7F5",
    paddingHorizontal: 12,
    paddingBottom: 12,
  },
  patientList: { marginBottom: 8, maxHeight: 224 },
  patientCard: {
    backgroundColor: "#fff",
    borderRadius: 14,
    paddingHorizontal: 16,
    paddingTop: 16,
    paddingBottom: 18,
    marginRight: 12,
    minWidth: 236,
    borderWidth: 1,
    borderColor: "#E0E0E0",
    borderLeftWidth: 6,
  },
  patientName: { fontSize: 16, fontWeight: "700" },
  patientUsername: { fontSize: 12, color: "#777", marginTop: 2 },
  patientActions: { marginTop: 12, gap: 9 },
  patientActionBtn: {
    minHeight: 42,
    borderRadius: 10,
    borderWidth: 1,
    backgroundColor: "#FAFCFF",
    paddingHorizontal: 12,
    paddingVertical: 8,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  patientActionBtnPressed: { backgroundColor: "#E7F0FA" },
  patientActionIcon: { width: 22, textAlign: "center", fontSize: 16, fontWeight: "700" },
  patientActionLabel: { fontSize: 14, color: "#222", fontWeight: "700" },
  liveSignalIcon: {
    width: 22,
    height: 18,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 2,
  },
  liveSignalDot: { width: 5, height: 5, borderRadius: 3 },
  liveSignalBar: { width: 3, borderRadius: 2 },
  tabRow: {
    flexDirection: "row",
    backgroundColor: "#E9EEF5",
    borderRadius: 10,
    padding: 3,
    marginBottom: 10,
  },
  tabBtn: { flex: 1, alignItems: "center", paddingVertical: 9, borderRadius: 8 },
  tabBtnActive: { backgroundColor: "#fff" },
  tabBtnPressed: { backgroundColor: "#DCE6F2" },
  tabText: { color: "#666", fontSize: 14, fontWeight: "700" },
  tabTextActive: { color: "#4A90D9" },
  alertList: { flex: 1 },
  alertCard: {
    backgroundColor: "#fff",
    borderRadius: 14,
    padding: 14,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: "#E0E0E0",
  },
  alertReason: { fontSize: 14, marginBottom: 6 },
  alertTime: { fontSize: 12, color: "#999", marginBottom: 6 },
  memoryText: { fontSize: 14, color: "#222", lineHeight: 20 },
  memoryMeta: { fontSize: 12, color: "#999", marginTop: 10 },
  closeBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#4A90D9",
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  closeBtnPressed: { backgroundColor: "#3B7FC4" },
  closeIcon: { color: "#fff", fontSize: 18, lineHeight: 18, fontWeight: "800" },
  closeLabel: { color: "#fff", fontSize: 14, fontWeight: "700" },
});
