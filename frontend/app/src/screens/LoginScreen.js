import React, { useState } from "react";
import {
  View,
  Text,
  TextInput,
  Pressable,
  StyleSheet,
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
} from "react-native";
import { login, register, setToken } from "../services/api";
import { saveSession } from "../services/session";

function RoleSelector({ role, onChange }) {
  return (
    <View style={styles.roleRow}>
      <Pressable
        style={[styles.roleBtn, role === "caregiver" && styles.roleBtnActive]}
        onPress={() => onChange("caregiver")}
      >
        <Text style={[styles.roleText, role === "caregiver" && styles.roleTextActive]}>
          Responsable
        </Text>
      </Pressable>
      <Pressable
        style={[styles.roleBtn, role === "patient" && styles.roleBtnActive]}
        onPress={() => onChange("patient")}
      >
        <Text style={[styles.roleText, role === "patient" && styles.roleTextActive]}>
          Paciente
        </Text>
      </Pressable>
    </View>
  );
}

export default function LoginScreen({ onLogin }) {
  const [isRegister, setIsRegister] = useState(false);
  const [identifier, setIdentifier] = useState("");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState("caregiver"); // "caregiver" | "patient"
  const [caregiverEmail, setCaregiverEmail] = useState("");
  const [loading, setLoading] = useState(false);

  const isPatient = role === "patient";

  const handleSubmit = async () => {
    const cleanFullName = fullName.trim();
    const cleanEmail = email.trim();
    const cleanUsername = username.trim();
    const cleanCaregiverEmail = caregiverEmail.trim();
    const cleanIdentifier = identifier.trim();

    if (!password) {
      Alert.alert("Error", "La contraseña es obligatoria");
      return;
    }

    if (!isRegister && !cleanIdentifier) {
      Alert.alert("Error", isPatient ? "El usuario es obligatorio" : "El email es obligatorio");
      return;
    }

    if (isRegister) {
      if (!cleanFullName) {
        Alert.alert("Error", "El nombre es obligatorio");
        return;
      }
      if (isPatient && !cleanUsername) {
        Alert.alert("Error", "El usuario del paciente es obligatorio");
        return;
      }
      if (!isPatient && !cleanEmail) {
        Alert.alert("Error", "El email del responsable es obligatorio");
        return;
      }
      if (isPatient && !cleanCaregiverEmail) {
        Alert.alert("Error", "Debes indicar el email del responsable");
        return;
      }
    }

    setLoading(true);
    try {
      let data;
      if (isRegister) {
        data = await register({
          email: isPatient ? null : cleanEmail,
          username: isPatient ? cleanUsername : null,
          password,
          fullName: cleanFullName,
          role,
          caregiverEmail: isPatient ? cleanCaregiverEmail : null,
        });
      } else {
        data = await login(cleanIdentifier, password, role);
      }
      setToken(data.access_token);
      await saveSession(data.access_token, data);
      onLogin(data);
    } catch (e) {
      Alert.alert("Error", e.message);
    } finally {
      setLoading(false);
    }
  };

  const loginPlaceholder = isPatient ? "Usuario del paciente" : "Email del responsable";

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "ios" ? "padding" : "height"}
    >
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <Text style={styles.title}>Asistente</Text>
        <Text style={styles.subtitle}>
          {isRegister ? "Crear cuenta" : "Iniciar sesión"}
        </Text>

        <RoleSelector role={role} onChange={setRole} />

        {isRegister ? (
          <>
            <TextInput
              style={styles.input}
              placeholder="Nombre completo"
              value={fullName}
              onChangeText={setFullName}
            />

            {isPatient ? (
              <>
                <TextInput
                  style={styles.input}
                  placeholder="Usuario del paciente"
                  value={username}
                  onChangeText={setUsername}
                  autoCapitalize="none"
                />
                <TextInput
                  style={styles.input}
                  placeholder="Email del responsable"
                  value={caregiverEmail}
                  onChangeText={setCaregiverEmail}
                  keyboardType="email-address"
                  autoCapitalize="none"
                />
              </>
            ) : (
              <TextInput
                style={styles.input}
                placeholder="Email del responsable"
                value={email}
                onChangeText={setEmail}
                keyboardType="email-address"
                autoCapitalize="none"
              />
            )}
          </>
        ) : (
          <TextInput
            style={styles.input}
            placeholder={loginPlaceholder}
            value={identifier}
            onChangeText={setIdentifier}
            keyboardType={isPatient ? "default" : "email-address"}
            autoCapitalize="none"
          />
        )}

        <TextInput
          style={styles.input}
          placeholder="Contraseña"
          value={password}
          onChangeText={setPassword}
          secureTextEntry
        />

        <Pressable
          style={[styles.button, loading && styles.buttonDisabled]}
          onPress={handleSubmit}
          disabled={loading}
        >
          <Text style={styles.buttonText}>
            {loading ? "Cargando..." : isRegister ? "Registrarse" : "Entrar"}
          </Text>
        </Pressable>

        <Pressable onPress={() => setIsRegister(!isRegister)}>
          <Text style={styles.link}>
            {isRegister ? "¿Ya tienes cuenta? Inicia sesión" : "¿No tienes cuenta? Regístrate"}
          </Text>
        </Pressable>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#F5F7FA" },
  scroll: { flexGrow: 1, justifyContent: "center", padding: 24 },
  title: { fontSize: 32, fontWeight: "800", textAlign: "center", marginBottom: 4 },
  subtitle: { fontSize: 18, textAlign: "center", color: "#666", marginBottom: 28 },
  input: {
    backgroundColor: "#fff",
    borderRadius: 12,
    padding: 14,
    fontSize: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: "#E0E0E0",
  },
  roleRow: { flexDirection: "row", gap: 10, marginBottom: 12 },
  roleBtn: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: "#E0E0E0",
    alignItems: "center",
    backgroundColor: "#fff",
  },
  roleBtnActive: { borderColor: "#4A90D9", backgroundColor: "#EBF3FC" },
  roleText: { fontSize: 15, color: "#666" },
  roleTextActive: { color: "#4A90D9", fontWeight: "700" },
  button: {
    backgroundColor: "#4A90D9",
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: "center",
    marginTop: 8,
  },
  buttonDisabled: { opacity: 0.6 },
  buttonText: { color: "#fff", fontSize: 18, fontWeight: "700" },
  link: { textAlign: "center", color: "#4A90D9", marginTop: 16, fontSize: 15 },
});
