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
import { getPatients, getAlerts, ackAlert } from "../services/api";

export default function CaregiverHomeScreen({ user, onLogout, onEditContext }) {
  const [patients, setPatients] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const [p, a] = await Promise.all([getPatients(), getAlerts()]);
      setPatients(p);
      setAlerts(a);
      setLoaded(true);
    } catch (e) {
      Alert.alert("Error", e.message);
    } finally {
      setRefreshing(false);
    }
  }, []);

  // Load on first render
  React.useEffect(() => {
    if (!loaded) refresh();
  }, [loaded, refresh]);

  const handleAck = async (alertId) => {
    try {
      await ackAlert(alertId);
      refresh();
    } catch (e) {
      Alert.alert("Error", e.message);
    }
  };

  const patientName = (patientId) => {
    const p = patients.find((p) => p.id === patientId);
    return p ? p.full_name : `Paciente #${patientId}`;
  };

  const newAlerts = alerts.filter((a) => a.status === "NEW");
  const pastAlerts = alerts.filter((a) => a.status !== "NEW");

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.greeting}>Hola, {user.full_name}</Text>
        <Pressable onPress={onLogout}>
          <Text style={styles.logout}>Salir</Text>
        </Pressable>
      </View>

      {/* Patients section */}
      <Text style={styles.sectionTitle}>Mis pacientes</Text>
      {patients.length === 0 && loaded ? (
        <Text style={styles.empty}>No hay pacientes vinculados aún.</Text>
      ) : (
        <FlatList
          data={patients}
          keyExtractor={(item) => String(item.id)}
          horizontal
          showsHorizontalScrollIndicator={false}
          style={styles.patientList}
          renderItem={({ item }) => (
            <Pressable
              style={styles.patientCard}
              onPress={() => onEditContext(item)}
            >
              <Text style={styles.patientName}>{item.full_name}</Text>
              <Text style={styles.patientSub}>Editar contexto →</Text>
            </Pressable>
          )}
        />
      )}

      {showHistory ? (
        <>
          <View style={styles.sectionRow}>
            <Text style={styles.sectionTitle}>Historial de alertas</Text>
            <Pressable style={styles.historyBtn} onPress={() => setShowHistory(false)}>
              <Text style={styles.historyIcon}>🔔</Text>
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
              <View style={styles.alertCard}>
                <View style={styles.alertHeader}>
                  <Text style={styles.alertPatient}>{patientName(item.patient_id)}</Text>
                  <Text style={styles.alertSeverity}>Sev: {item.severity}/5</Text>
                </View>
                <Text style={styles.alertReason}>{item.reason}</Text>
                {item.llm_response && (
                  <Text style={styles.alertLlm}>Respuesta IA: {item.llm_response}</Text>
                )}
                <Text style={styles.alertTime}>
                  {new Date(item.created_at).toLocaleString("es-ES")}
                </Text>
              </View>
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
              <Text style={styles.historyIcon}>🕓</Text>
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
              <View style={[styles.alertCard, styles.alertNew]}>
                <View style={styles.alertHeader}>
                  <Text style={styles.alertPatient}>{patientName(item.patient_id)}</Text>
                  <Text style={styles.alertSeverity}>Sev: {item.severity}/5</Text>
                </View>
                <Text style={styles.alertReason}>{item.reason}</Text>
                {item.llm_response && (
                  <Text style={styles.alertLlm}>Respuesta IA: {item.llm_response}</Text>
                )}
                <View style={styles.alertFooter}>
                  <Text style={styles.alertTime}>
                    {new Date(item.created_at).toLocaleString("es-ES")}
                  </Text>
                  <Pressable style={styles.ackBtn} onPress={() => handleAck(item.id)}>
                    <Text style={styles.ackText}>✓ Aceptar</Text>
                  </Pressable>
                </View>
              </View>
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
  greeting: { fontSize: 22, fontWeight: "700" },
  logout: { color: "#E74C3C", fontSize: 16 },
  historyBtn: { flexDirection: "row", alignItems: "center", gap: 4 },
  historyIcon: { fontSize: 18 },
  historyLabel: { color: "#4A90D9", fontSize: 14, fontWeight: "600" },
  sectionRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 16, marginBottom: 10 },
  sectionTitle: { fontSize: 18, fontWeight: "700" },
  empty: { color: "#999", marginBottom: 10 },
  patientList: { marginBottom: 8, maxHeight: 100 },
  patientCard: {
    backgroundColor: "#fff",
    borderRadius: 14,
    padding: 16,
    marginRight: 12,
    minWidth: 160,
    borderWidth: 1,
    borderColor: "#E0E0E0",
  },
  patientName: { fontSize: 16, fontWeight: "700" },
  patientSub: { fontSize: 13, color: "#4A90D9", marginTop: 4 },
  alertList: { flex: 1 },
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
});
