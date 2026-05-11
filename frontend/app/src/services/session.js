/**
 * Session persistence.
 *
 * Wraps expo-secure-store with a tiny object-serialized API. The token is
 * stored separately from the user payload so the api layer can set it as
 * early as possible at boot without deserializing the whole session.
 */
import * as SecureStore from "expo-secure-store";
import { setToken } from "./api";

const TOKEN_KEY = "tfg_token";
const USER_KEY = "tfg_user";
const PATIENT_TTS_PREFIX = "tfg_patient_tts_enabled_";

export async function saveSession(token, user) {
  try {
    await SecureStore.setItemAsync(TOKEN_KEY, token);
    await SecureStore.setItemAsync(USER_KEY, JSON.stringify(user));
    setToken(token);
  } catch (e) {
    console.warn("saveSession failed:", e?.message || e);
  }
}

export async function loadSession() {
  try {
    const token = await SecureStore.getItemAsync(TOKEN_KEY);
    const userRaw = await SecureStore.getItemAsync(USER_KEY);
    if (!token || !userRaw) return null;
    const user = JSON.parse(userRaw);
    setToken(token);
    return { token, user };
  } catch (e) {
    console.warn("loadSession failed:", e?.message || e);
    return null;
  }
}

export async function clearSession() {
  try {
    await SecureStore.deleteItemAsync(TOKEN_KEY);
    await SecureStore.deleteItemAsync(USER_KEY);
  } catch (e) {
    console.warn("clearSession failed:", e?.message || e);
  } finally {
    setToken(null);
  }
}

export async function savePatientTtsEnabled(userId, enabled) {
  if (!userId) return;
  try {
    await SecureStore.setItemAsync(`${PATIENT_TTS_PREFIX}${userId}`, enabled ? "1" : "0");
  } catch (e) {
    console.warn("savePatientTtsEnabled failed:", e?.message || e);
  }
}

export async function loadPatientTtsEnabled(userId) {
  if (!userId) return true;
  try {
    const raw = await SecureStore.getItemAsync(`${PATIENT_TTS_PREFIX}${userId}`);
    if (raw == null) return true;
    return raw === "1";
  } catch (e) {
    console.warn("loadPatientTtsEnabled failed:", e?.message || e);
    return true;
  }
}
