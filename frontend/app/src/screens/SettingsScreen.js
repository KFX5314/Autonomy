/**
 * Role-neutral Settings screen.
 *
 * Shows current account info, app version, a few stubbed future-features,
 * and a prominent red "Cerrar sesión" action. Animated entry: fade + slide up.
 */
import React, { useEffect, useRef } from "react";
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  ScrollView,
  Animated,
  Alert as RNAlert,
} from "react-native";
import Constants from "expo-constants";

export default function SettingsScreen({ navigation, route }) {
  const user = route?.params?.user;
  const onLogout = route?.params?.onLogout;

  const fade = useRef(new Animated.Value(0)).current;
  const translate = useRef(new Animated.Value(16)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.timing(fade, { toValue: 1, duration: 250, useNativeDriver: true }),
      Animated.timing(translate, { toValue: 0, duration: 250, useNativeDriver: true }),
    ]).start();
  }, [fade, translate]);

  const stub = (title) => () =>
    RNAlert.alert(title, "Próximamente.", [{ text: "OK" }]);

  const version =
    Constants?.expoConfig?.version ||
    Constants?.manifest?.version ||
    "0.1.0";

  return (
    <Animated.View style={[styles.wrap, { opacity: fade, transform: [{ translateY: translate }] }]}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Ajustes</Text>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Cuenta</Text>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Correo</Text>
            <Text style={styles.rowValue}>{user?.email || "—"}</Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Rol</Text>
            <Text style={styles.rowValue}>
              {user?.role === "caregiver" ? "Cuidador" : user?.role === "patient" ? "Paciente" : "—"}
            </Text>
          </View>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Preferencias</Text>
          <Pressable style={styles.item} onPress={stub("Cambiar contraseña")}>
            <Text style={styles.itemLabel}>Cambiar contraseña</Text>
            <Text style={styles.itemArrow}>›</Text>
          </Pressable>
          <Pressable style={styles.item} onPress={stub("Tema oscuro")}>
            <Text style={styles.itemLabel}>Tema oscuro</Text>
            <Text style={styles.itemArrow}>›</Text>
          </Pressable>
          <Pressable style={styles.item} onPress={stub("Notificaciones")}>
            <Text style={styles.itemLabel}>Notificaciones</Text>
            <Text style={styles.itemArrow}>›</Text>
          </Pressable>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Acerca de</Text>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Versión</Text>
            <Text style={styles.rowValue}>{version}</Text>
          </View>
        </View>

        <Pressable
          style={styles.logoutBtn}
          onPress={() => {
            if (onLogout) onLogout();
          }}
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
    paddingHorizontal: 12,
    paddingVertical: 14,
    borderTopWidth: 1,
    borderTopColor: "#F1F1F1",
  },
  itemLabel: { fontSize: 15, color: "#222" },
  itemArrow: { fontSize: 20, color: "#BBB" },
  logoutBtn: {
    backgroundColor: "#E74C3C",
    borderRadius: 14,
    paddingVertical: 16,
    alignItems: "center",
    marginTop: 10,
  },
  logoutText: { color: "#fff", fontSize: 17, fontWeight: "700" },
});
