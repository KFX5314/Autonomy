import appConfig from "../config/appConfig";

const { api } = appConfig;

let _token = null;
let _onUnauthorized = null;

export function setToken(token) {
  _token = token;
}

export function getToken() {
  return _token;
}

export function setUnauthorizedHandler(handler) {
  _onUnauthorized = handler;
}

function makeApiError(res, text) {
  let detail = text;
  try {
    detail = JSON.parse(text).detail || text;
  } catch {}
  const error = new Error(detail || `HTTP ${res.status}`);
  error.status = res.status;
  return error;
}

function throwIfUnauthorized(error) {
  if (error.status === 401 && _token && _onUnauthorized) {
    _onUnauthorized();
  }
}

async function request(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...options.headers,
  };

  if (_token) {
    headers["Authorization"] = `Bearer ${_token}`;
  }

  const res = await fetch(`${api.baseUrl}${path}`, { ...options, headers });
  const text = await res.text();

  if (!res.ok) {
    const error = makeApiError(res, text);
    throwIfUnauthorized(error);
    throw error;
  }

  return text ? JSON.parse(text) : null;
}

// Auth
export async function login(identifier, password, role) {
  return request("/auth/login", {
    method: "POST",
    body: JSON.stringify({ identifier, password, role }),
  });
}

export async function register({ email, password, fullName, role }) {
  return request("/auth/register", {
    method: "POST",
    body: JSON.stringify({
      email: email || null,
      password,
      full_name: fullName,
      role,
    }),
  });
}

export async function getCurrentUser() {
  return request("/auth/me");
}

// Patients
export async function getPatients() {
  return request("/patients/");
}

export async function createPatientForCaregiver({ fullName, username, password }) {
  return request("/patients/", {
    method: "POST",
    body: JSON.stringify({
      full_name: fullName,
      username: username || null,
      password,
    }),
  });
}

export async function updatePatient(patientId, { username }) {
  return request(`/patients/${patientId}`, {
    method: "PATCH",
    body: JSON.stringify({ username }),
  });
}

export async function deletePatient(patientId) {
  return request(`/patients/${patientId}`, {
    method: "DELETE",
  });
}

export async function getPatientContext(patientId) {
  return request(`/patients/${patientId}/context`);
}

export async function getMyPatientSettings() {
  return request("/patients/me/settings");
}

export async function updatePatientContext(patientId, contextJson) {
  return request(`/patients/${patientId}/context`, {
    method: "PUT",
    body: JSON.stringify({ context_json: contextJson }),
  });
}

export async function sendPatientLogoutWarning() {
  return request("/patients/me/logout-warning", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

// Journal and memory
export async function getPatientJournal(patientId, sinceHours = 24, limit = 100) {
  return request(`/patients/${patientId}/journal?since_hours=${sinceHours}&limit=${limit}`);
}

export async function getPatientShortTermMemory(patientId) {
  return request(`/patients/${patientId}/short-term-memory`);
}

export async function getVoiceSamples(patientId) {
  return request(`/patients/${patientId}/voice-samples`);
}

export async function deleteVoiceSample(patientId, sampleId) {
  return request(`/patients/${patientId}/voice-samples/${sampleId}`, {
    method: "DELETE",
  });
}

// Alerts
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

export async function registerPushToken({ token, platform, deviceId }) {
  return request("/push-tokens/", {
    method: "POST",
    body: JSON.stringify({
      token,
      platform: platform || null,
      device_id: deviceId || null,
    }),
  });
}

export async function deletePushToken(token) {
  return request(`/push-tokens/?token=${encodeURIComponent(token)}`, {
    method: "DELETE",
  });
}

// Audio.Sound accepts auth headers when loading protected alert audio.
export function getAlertAudioUrl(alertId) {
  return `${api.baseUrl}/alerts/${alertId}/audio`;
}

export function getAuthHeader() {
  return _token ? { Authorization: `Bearer ${_token}` } : {};
}

// Audio upload

async function _sendAudioChunkOnce(uri, metadata = {}) {
  const form = new FormData();
  form.append("file", {
    uri,
    name: "audio.m4a",
    type: "audio/mp4",
  });
  if (metadata.recentTtsText) {
    form.append("recent_tts_text", metadata.recentTtsText);
  }
  if (metadata.recentTtsAgeMs != null) {
    form.append("recent_tts_age_ms", String(metadata.recentTtsAgeMs));
  }

  const headers = {};
  if (_token) {
    headers["Authorization"] = `Bearer ${_token}`;
  }

  // Abort the request if it takes too long (backend processing can be slow
  // on first call, but >30s is almost certainly a dead connection).
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), api.audioChunkTimeoutMs);

  try {
    // Let fetch generate the multipart boundary.
    const res = await fetch(`${api.baseUrl}/audio/chunk`, {
      method: "POST",
      body: form,
      headers,
      signal: controller.signal,
    });

    const text = await res.text();
    if (!res.ok) {
      const error = makeApiError(res, text);
      throwIfUnauthorized(error);
      throw error;
    }
    return JSON.parse(text);
  } finally {
    clearTimeout(timer);
  }
}

export async function sendAudioChunk(uri, metadata = {}) {
  for (let attempt = 0; attempt <= api.audioChunkMaxRetries; attempt++) {
    try {
      return await _sendAudioChunkOnce(uri, metadata);
    } catch (e) {
      if (e.status === 401) throw e;
      const isLast = attempt >= api.audioChunkMaxRetries;
      if (isLast) throw e;
      console.warn(`[API] Audio chunk attempt ${attempt + 1} failed: ${e.message} — retrying...`);
      await new Promise((r) => setTimeout(r, api.audioChunkRetryDelayMs));
    }
  }
}

// Voice enrollment
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

  const res = await fetch(`${api.baseUrl}/patients/${patientId}/voice-sample`, {
    method: "POST",
    body: form,
    headers,
  });

  const text = await res.text();
  if (!res.ok) {
    const error = makeApiError(res, text);
    throwIfUnauthorized(error);
    throw error;
  }
  return JSON.parse(text);
}

// Health
export async function healthCheck() {
  return request("/health");
}
