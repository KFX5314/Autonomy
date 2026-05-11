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
} from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import appConfig from "../config/appConfig";
import {
  getPatients,
  getAlerts,
  ackAlert,
  getPatientJournal,
  getPatientShortTermMemory,
} from "../services/api";
import AlertCard from "../components/AlertCard";

const { caregiver } = appConfig;

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

  const refresh = useCallback(async ({ silent = false, showSpinner = true } = {}) => {
    if (showSpinner) setRefreshing(true);
    try {
      const [p, a] = await Promise.all([getPatients(), getAlerts()]);
      setPatients(p);
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

  const loadShortTermMemory = useCallback(async (patientId, { silent = false } = {}) => {
    setStmLoading(true);
    try {
      const data = await getPatientShortTermMemory(patientId);
      setShortTermMemory(data);
    } catch (e) {
      if (!silent) Alert.alert("Error", e.message);
    } finally {
      setStmLoading(false);
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
            <View style={styles.patientCard}>
              <Text style={styles.patientName}>{item.full_name}</Text>
              <View style={styles.patientActions}>
                <Pressable onPress={() => onEditContext(item)}>
                  <Text style={styles.patientSub}>Editar contexto</Text>
                </Pressable>
                <Pressable onPress={() => openPatientDetail(item, "journal")}>
                  <Text style={styles.patientSub}>Ver diario</Text>
                </Pressable>
                <Pressable onPress={() => openPatientDetail(item, "advanced")}>
                  <Text style={styles.patientSub}>Avanzado</Text>
                </Pressable>
              </View>
            </View>
          )}
        />
      )}

      {detailPatient ? (
        <>
          <View style={styles.sectionRow}>
            <Text style={styles.sectionTitle}>{detailPatient.name}</Text>
            <Pressable style={styles.historyBtn} onPress={closePatientDetail}>
              <Text style={styles.historyLabel}>Cerrar</Text>
            </Pressable>
          </View>

          <View style={styles.tabRow}>
            <Pressable
              style={[styles.tabBtn, detailTab === "journal" && styles.tabBtnActive]}
              onPress={() => setDetailTab("journal")}
            >
              <Text style={[styles.tabText, detailTab === "journal" && styles.tabTextActive]}>
                Diario
              </Text>
            </Pressable>
            <Pressable
              style={[styles.tabBtn, detailTab === "advanced" && styles.tabBtnActive]}
              onPress={() => setDetailTab("advanced")}
            >
              <Text style={[styles.tabText, detailTab === "advanced" && styles.tabTextActive]}>
                Avanzado
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
        </>
      ) : showHistory ? (
        <>
          <View style={styles.sectionRow}>
            <Text style={styles.sectionTitle}>Historial de alertas</Text>
            <Pressable style={styles.historyBtn} onPress={() => setShowHistory(false)}>
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
            <Pressable style={styles.historyBtn} onPress={() => setShowHistory(true)}>
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
  historyBtn: { flexDirection: "row", alignItems: "center", gap: 4 },
  historyLabel: { color: "#4A90D9", fontSize: 14, fontWeight: "600" },
  sectionRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 16, marginBottom: 10 },
  sectionTitle: { fontSize: 18, fontWeight: "700" },
  empty: { color: "#999", marginBottom: 10 },
  patientList: { marginBottom: 8, maxHeight: 126 },
  patientCard: {
    backgroundColor: "#fff",
    borderRadius: 14,
    padding: 14,
    marginRight: 12,
    minWidth: 170,
    borderWidth: 1,
    borderColor: "#E0E0E0",
  },
  patientName: { fontSize: 16, fontWeight: "700" },
  patientActions: { marginTop: 4, gap: 3 },
  patientSub: { fontSize: 13, color: "#4A90D9", marginTop: 3 },
  tabRow: {
    flexDirection: "row",
    backgroundColor: "#E9EEF5",
    borderRadius: 10,
    padding: 3,
    marginBottom: 10,
  },
  tabBtn: { flex: 1, alignItems: "center", paddingVertical: 9, borderRadius: 8 },
  tabBtnActive: { backgroundColor: "#fff" },
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
});
