/**
 * API service - single source of truth for backend communication.
 */

// Set this to your backend URL (Tailscale IP or local)
const BASE_URL = process.env.EXPO_PUBLIC_SERVER_URL || "http://100.64.0.1:8000";

let _token = null;

export function setToken(token) {
  _token = token;
}

export function getToken() {
  return _token;
}

async function request(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...options.headers,
  };

  if (_token) {
    headers["Authorization"] = `Bearer ${_token}`;
  }

  const res = await fetch(`${BASE_URL}${path}`, { ...options, headers });
  const text = await res.text();

  if (!res.ok) {
    let detail = text;
    try {
      detail = JSON.parse(text).detail || text;
    } catch {}
    throw new Error(detail);
  }

  return text ? JSON.parse(text) : null;
}

// ─── Auth ─────────────────────────────────────────────
export async function login(email, password) {
  return request("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function register(email, password, fullName, role, caregiverEmail) {
  return request("/auth/register", {
    method: "POST",
    body: JSON.stringify({
      email,
      password,
      full_name: fullName,
      role,
      caregiver_email: caregiverEmail || null,
    }),
  });
}

// ─── Patients (caregiver) ─────────────────────────────
export async function getPatients() {
  return request("/patients/");
}

export async function getPatientContext(patientId) {
  return request(`/patients/${patientId}/context`);
}

export async function updatePatientContext(patientId, contextJson) {
  return request(`/patients/${patientId}/context`, {
    method: "PUT",
    body: JSON.stringify({ context_json: contextJson }),
  });
}

// ─── Alerts (caregiver) ──────────────────────────────
export async function getAlerts(patientId, status) {
  let path = "/alerts/";
  const params = [];
  if (patientId) params.push(`patient_id=${patientId}`);
  if (status) params.push(`status=${status}`);
  if (params.length) path += `?${params.join("&")}`;
  return request(path);
}

export async function ackAlert(alertId, status = "ACK") {
  return request(`/alerts/${alertId}/ack`, {
    method: "POST",
    body: JSON.stringify({ status }),
  });
}

// ─── Audio (patient) ─────────────────────────────────
export async function sendAudioChunk(uri) {
  const form = new FormData();
  form.append("file", {
    uri,
    name: "audio.m4a",
    type: "audio/mp4",
  });

  const headers = {};
  if (_token) {
    headers["Authorization"] = `Bearer ${_token}`;
  }
  // Do NOT set Content-Type manually — fetch auto-generates the boundary for FormData
  const res = await fetch(`${BASE_URL}/audio/chunk`, {
    method: "POST",
    body: form,
    headers,
  });

  const text = await res.text();
  if (!res.ok) throw new Error(text);
  return JSON.parse(text);
}

// ─── Voice enrollment (caregiver) ────────────────────
export async function uploadVoiceSample(patientId, uri) {
  const form = new FormData();
  form.append("file", {
    uri,
    name: "voice-sample.m4a",
    type: "audio/mp4",
  });

  const headers = {};
  if (_token) {
    headers["Authorization"] = `Bearer ${_token}`;
  }

  const res = await fetch(`${BASE_URL}/patients/${patientId}/voice-sample`, {
    method: "POST",
    body: form,
    headers,
  });

  const text = await res.text();
  if (!res.ok) throw new Error(text);
  return JSON.parse(text);
}

// ─── Health ──────────────────────────────────────────
export async function healthCheck() {
  return request("/health");
}
