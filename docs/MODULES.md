# Documentación de módulos - TFG-DEMENCIA

Este documento explica en detalle cómo funciona cada módulo del sistema.

---

## 1. Backend (`backend/src/`)

### 1.1 `server.py` - Entry Point

El punto de entrada de la aplicación FastAPI. Responsabilidades:
- Inicializa la app con CORS habilitado (necesario para peticiones desde Expo).
- Registra todos los routers (auth, patients, audio, alerts).
- En el evento `lifespan`, ejecuta `Base.metadata.create_all()` para crear las tablas automáticamente si no existen (conveniente para desarrollo).
- Endpoint `/health` verifica el estado del backend y la disponibilidad del LLM.

### 1.2 `config.py` - Configuración centralizada

Dataclass que carga toda la configuración desde variables de entorno con defaults sensibles para desarrollo local. Se instancia como singleton `config` al importar.

Diseño: un único punto de verdad para configuración. Si se necesitara `.env` file support, se añadiría `python-dotenv` sin cambiar la estructura.

### 1.3 `database.py` - Conexión a MariaDB

Configura SQLAlchemy con:
- `create_engine()` para crear el pool de conexiones.
- `SessionLocal` como fábrica de sesiones.
- `get_db()` como dependency para FastAPI (patrón yield para auto-cerrar sesiones).
- `Base` como clase base declarativa para todos los modelos ORM.

### 1.4 `auth.py` - Autenticación JWT

Sistema de autenticación basado en tokens JWT:
- **`hash_password()`**: Hashea con bcrypt vía passlib.
- **`verify_password()`**: Verifica plain vs hash.
- **`create_access_token()`**: Genera JWT con `sub` (user_id) y `role`, expiración configurable.
- **`get_current_user()`**: Dependency de FastAPI que extrae y valida el JWT del header `Authorization: Bearer <token>`.
- **`require_caregiver()`** / **`require_patient()`**: Dependencies que además verifican el rol.

Flujo:
```
Login → JWT emitido → Cliente envía en header → get_current_user() valida → require_X() verifica rol
```

### 1.5 `models/` - Modelos ORM (SQLAlchemy)

| Modelo | Tabla | Descripción |
|---|---|---|
| `User` | `users` | Usuarios del sistema (cuidadores y pacientes). Campo `role` discrimina. Campo `caregiver_id` vincula paciente→cuidador. |
| `Patient` | `patients` | Perfil extendido del paciente (1:1 con User donde role='patient'). |
| `PatientContext` | `patient_context` | JSON flexible con el contexto personalizado del paciente. 1:1 con Patient. |
| `Transcript` | `transcripts` | Cada transcripción generada por Whisper. Vinculada al paciente. |
| `Alert` | `alerts` | Alertas generadas por episodios detectados. Estados: NEW→ACK. |
| `ConversationHistory` | `conversation_history` | Historial de conversación en modo asistente (futuro multi-turno). |

**Relaciones clave:**
```
User(caregiver) ──1:N──> User(patient) ──1:1──> Patient ──1:1──> PatientContext
                                                    │
                                                    ├──1:N──> Transcript ──1:1──> Alert
                                                    └──1:N──> Alert ──1:N──> ConversationHistory
```

### 1.6 `schemas/` - Schemas Pydantic

Definen la estructura de request/response para la API:
- `auth.py`: `RegisterRequest`, `LoginRequest`, `TokenResponse`, `UserOut`
- `patient.py`: `PatientOut`, `PatientContextUpdate`, `PatientContextOut`
- `alert.py`: `AlertOut`, `AlertAck`, `AudioChunkResponse`

Las schemas usan `from_attributes = True` para serializar directamente desde objetos SQLAlchemy.

### 1.7 `routes/` - Endpoints de la API

#### `routes/auth.py`
- **POST `/auth/register`**: Crea usuario (caregiver o patient). Si es paciente, crea también el perfil Patient y un contexto por defecto con frases gatillo básicas ("ayuda", "no sé dónde estoy").
- **POST `/auth/login`**: Verifica credenciales, devuelve JWT + info del usuario.

#### `routes/patients.py`
- **GET `/patients/`**: Lista los pacientes vinculados al cuidador autenticado.
- **GET `/patients/{id}/context`**: Devuelve el JSON de contexto. Verifica que el paciente pertenece al cuidador.
- **PUT `/patients/{id}/context`**: Actualiza el contexto completo (reemplaza el JSON).

#### `routes/audio.py`
- **POST `/audio/chunk`**: Endpoint principal del sistema. Recibe un archivo de audio (multipart), ejecuta el pipeline completo:
  1. Guarda en archivo temporal.
  2. Transcribe con Whisper (STT).
  3. Si el texto está vacío, devuelve "no episodio".
  4. Almacena la transcripción en BD.
  5. Carga el contexto del paciente.
  6. Ejecuta `EpisodeDetector.analyze()`.
  7. Si es episodio, crea alerta en BD.
  8. Devuelve resultado al móvil (incluyendo texto para TTS).
  9. Elimina el archivo temporal (privacidad).

#### `routes/alerts.py`
- **GET `/alerts/`**: Lista alertas de los pacientes del cuidador. Filtros opcionales por `patient_id` y `status`.
- **POST `/alerts/{id}/ack`**: Cambia el estado de una alerta a ACK.

### 1.8 `services/stt_service.py` - Transcripción

Wrapper alrededor de OpenAI Whisper:
- Carga el modelo de forma lazy (singleton) en el device configurado (GPU/CPU).
- `transcribe_audio()` recibe un path de archivo y devuelve texto + idioma.
- Modelo configurable via `STT_MODEL` (base, small, medium, large-v3-turbo).

### 1.9 `services/episode_detector.py` - Detección de episodios

Motor de detección en **dos fases**:

**Fase 1 - Reglas (determinista, instantánea):**
- Busca coincidencias exactas con `trigger_phrases` del contexto.
- Busca matches regex con `risk_rules`.
- Si hay coincidencia de severidad ≥ 4, responde inmediatamente.

**Fase 2 - LLM (contextual, más lenta):**
- Solo se ejecuta si la Fase 1 no encontró nada.
- Envía un prompt de análisis al LLM con las reglas del contexto y la transcripción.
- Espera respuesta en JSON: `{episode: bool, severity: int, reason: str}`.
- Si se detecta episodio, hace una segunda llamada al LLM para generar un mensaje calmante.

**Generación de respuesta:**
- Construye un system prompt con el perfil del paciente (nombre, ubicación, cuidadores).
- El LLM genera un mensaje corto, calmado, en español.
- Este texto se devuelve al móvil para TTS.

### 1.10 `services/llm/` - Strategy Pattern para proveedores LLM

**Patrón de diseño: Strategy + Factory**

```
         ┌──────────────┐
         │ LLMProvider   │  (Abstract Base Class)
         │  + generate() │
         │  + health()   │
         └──────┬───────┘
                │
        ┌───────┴────────┐
        │                │
┌───────┴──────┐  ┌──────┴───────┐
│OllamaProvider│  │OpenAIProvider│
│  Ollama API  │  │ OpenAI compat│
└──────────────┘  └──────────────┘
        ▲
        │ get_llm_provider()
┌───────┴──────┐
│   Factory     │  Lee config.LLM_PROVIDER
└──────────────┘   y devuelve la instancia
```

- **`base.py`**: Define la interfaz `LLMProvider` con dos métodos abstractos: `generate()` y `health_check()`.
- **`ollama_provider.py`**: Implementación que llama a la API HTTP de Ollama (`/api/chat`).
- **`openai_provider.py`**: Implementación compatible con la API de OpenAI. Funciona con OpenAI, Azure OpenAI, OpenRouter, o cualquier API compatible.
- **`factory.py`**: `get_llm_provider()` lee `config.LLM_PROVIDER` y devuelve la instancia correcta (singleton).

**Para añadir un nuevo proveedor** (ej: Claude, Gemini):
1. Crear `claude_provider.py` que implemente `LLMProvider`.
2. Añadir un caso en `factory.py`.
3. Sin cambios en el resto del código.

---

## 2. Frontend (`frontend/app/`)

### 2.1 `App.js` - Root con routing por rol

Componente raíz que maneja el estado de sesión:
- Si no hay usuario: muestra `LoginScreen`.
- Si usuario con `role === "caregiver"`: muestra `CaregiverHomeScreen` (o `PatientContextScreen` si está editando).
- Si usuario con `role === "patient"`: muestra `PatientHomeScreen`.

No usa react-navigation (mantenido simple con estado). Se puede migrar a navigation si crece la app.

### 2.2 `screens/LoginScreen.js`

Pantalla de login/registro unificada:
- Toggle entre "Iniciar sesión" y "Registrarse".
- En modo registro, muestra selector de rol (Responsable/Paciente).
- Si el rol es "Paciente", pide el email del responsable (para vincular cuentas).
- Tras autenticarse, guarda el token y llama `onLogin(data)`.

### 2.3 `screens/PatientHomeScreen.js`

Interfaz del paciente - modo escucha:
- Botón circular grande para activar/desactivar la escucha.
- Cuando está activo, graba audio en chunks de 15 segundos.
- Ciclo: grabar → parar → enviar al backend → grabar de nuevo.
- Si el backend responde con `episode: true`:
  - Muestra el mensaje del asistente.
  - Lo reproduce en voz alta con `expo-speech` (TTS nativo).
  - Indica que el cuidador ha sido avisado.

### 2.4 `screens/CaregiverHomeScreen.js`

Dashboard del cuidador:
- **Lista horizontal de pacientes**: tarjetas tocables que abren el editor de contexto.
- **Lista de alertas**: con pull-to-refresh, alertas nuevas resaltadas en rojo.
- Cada alerta muestra: paciente, severidad, razón, respuesta del LLM, timestamp.
- Botón "Aceptar" para cambiar estado de NEW → ACK.

### 2.5 `screens/PatientContextScreen.js`

Editor de contexto del paciente:
- Campos editables: nombre preferido, dirección, cuidadores, notas médicas.
- **Frases gatillo**: una por línea, formato `frase|severidad` (ej: `ayuda|5`).
- **Reglas de riesgo**: una por línea, formato `patrón|riesgo` (ej: `autobús|bus|tendencia a desorientarse`).
- Botón "Guardar" que envía el JSON completo al backend.

### 2.6 `services/api.js`

Cliente API centralizado:
- Gestión de token JWT (set/get).
- Función `request()` base que añade headers de auth y maneja errores.
- Funciones exportadas para cada endpoint: `login()`, `register()`, `getPatients()`, `sendAudioChunk()`, etc.
- `sendAudioChunk()` usa `FormData` para enviar el archivo de audio como multipart.

---

## 3. Base de datos (`backend/init_db.sql`)

### Diagrama ER

```
users (id, email, password_hash, full_name, role, caregiver_id)
  │
  ├─ role='caregiver': caregiver_id = NULL
  │
  └─ role='patient': caregiver_id → users.id
        │
        └─ patients (id, user_id → users.id, birth_date, notes)
              │
              ├─ patient_context (patient_id → patients.id, context_json, updated_at)
              │
              ├─ transcripts (id, patient_id, started_at, ended_at, transcript_text, stt_model)
              │     │
              │     └─ alerts (id, patient_id, transcript_id, severity, reason, llm_response, status)
              │           │
              │           └─ conversation_history (id, alert_id, role, message)
              │
              └─ alerts (patient_id → patients.id)
```

### Campo `context_json`

Estructura JSON flexible que contiene:
- `static_profile`: nombre, dirección, cuidadores, notas médicas.
- `trigger_phrases`: frases que disparan alerta directa, con severidad.
- `risk_rules`: patrones regex que indican riesgo.
- `assistant_style`: configuración del tono/idioma/longitud del asistente.

Esta estructura puede evolucionar sin migraciones de esquema.

---

## 4. Flujo de datos completo

```
1. [Paciente App] Graba 15s de audio
         │
2. [Paciente App] POST /audio/chunk (multipart: archivo audio)
         │
3. [Backend] Guarda en /tmp, llama Whisper
         │
4. [Whisper CUDA] Transcribe audio → texto español
         │
5. [Backend] Guarda Transcript en MariaDB
         │
6. [Backend] Carga PatientContext del paciente
         │
7. [EpisodeDetector] Fase 1: regex/keyword matching
         │
         ├── Match → genera respuesta LLM (si disponible)
         │
         └── No match → Fase 2: envía al LLM para análisis contextual
                              │
                              └── LLM responde JSON {episode, severity, reason}
                                       │
                                       ├── episode=true → genera mensaje calmante + crea Alert
                                       │
                                       └── episode=false → no acción
         │
8. [Backend] Devuelve AudioChunkResponse al móvil
         │
9. [Paciente App] Si episode=true:
         │    - Muestra mensaje
         │    - TTS: lee el mensaje en voz alta
         │
10. [Cuidador App] GET /alerts/ → ve nueva alerta → ACK
```
