/**
 * TFG-DEMENCIA - Unified app with role-based login.
 * Caregivers see patient management + alerts.
 * Patients see the listening interface.
 */
import React, { useState } from "react";
import { StatusBar } from "expo-status-bar";
import { setToken } from "./src/services/api";
import LoginScreen from "./src/screens/LoginScreen";
import PatientHomeScreen from "./src/screens/PatientHomeScreen";
import CaregiverHomeScreen from "./src/screens/CaregiverHomeScreen";
import PatientContextScreen from "./src/screens/PatientContextScreen";

export default function App() {
  const [user, setUser] = useState(null); // { access_token, role, user_id, full_name }
  const [editingPatient, setEditingPatient] = useState(null);

  const handleLogin = (data) => {
    setUser(data);
  };

  const handleLogout = () => {
    setToken(null);
    setUser(null);
    setEditingPatient(null);
  };

  // Not logged in
  if (!user) {
    return (
      <>
        <StatusBar style="dark" />
        <LoginScreen onLogin={handleLogin} />
      </>
    );
  }

  // Caregiver editing a patient context
  if (user.role === "caregiver" && editingPatient) {
    return (
      <>
        <StatusBar style="dark" />
        <PatientContextScreen
          patient={editingPatient}
          onBack={() => setEditingPatient(null)}
        />
      </>
    );
  }

  // Caregiver home
  if (user.role === "caregiver") {
    return (
      <>
        <StatusBar style="dark" />
        <CaregiverHomeScreen
          user={user}
          onLogout={handleLogout}
          onEditContext={(patient) => setEditingPatient(patient)}
        />
      </>
    );
  }

  // Patient home
  return (
    <>
      <StatusBar style="dark" />
      <PatientHomeScreen user={user} onLogout={handleLogout} />
    </>
  );
}
