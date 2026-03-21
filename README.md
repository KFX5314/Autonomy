# TFG-DEMENCIA: Asistente IA para personas con demencia

## Descripción

Aplicación móvil + backend que actúa como asistente para personas con demencia y Alzheimer. El sistema escucha continuamente a través del micrófono del móvil del paciente, transcribe el audio, analiza el contenido contra un contexto personalizado y detecta episodios de desorientación o necesidad de ayuda. Cuando se detecta un episodio, notifica al cuidador y #TODO responde al paciente con un mensaje de orientación por voz.

## Arquitectura general

```
┌─────────────────┐     Audio chunks      ┌──────────────────────────────────┐
│  App Móvil      │ ────────────────────► │  Backend (FastAPI)               │
│  (Expo/RN)      │ ◄──────────────────── │                                  │
│                 │    Respuesta JSON      │  ┌─────────┐  ┌──────────────┐  │
│  Rol: Paciente  │                       │  │ Whisper  │  │ Detector de  │  │
│    - Graba      │                       │  │  (CUDA)  │  │  Episodios   │  │
│    - TTS resp.  │                       │  └─────────┘  └──────────────┘  │
│                 │                       │                                  │
│  Rol: Cuidador  │                       │  ┌─────────┐  ┌──────────────┐  │
│    - Contexto   │ ────────────────────► │  │ Ollama   │  │  MariaDB     │  │
│    - Alertas    │     CRUD REST         │  │(phi-3/LLM│  │              │  │
└─────────────────┘                       │  └─────────┘  └──────────────┘  │
                                          └──────────────────────────────────┘
```

## Requisitos previos

| Componente | Versión mínima | Notas |
|---|---|---|
| Python | 3.11+ | Backend |
| Node.js | 18+ | Frontend Expo |
| MariaDB | 10.6+ | Base de datos |
| Ollama | Latest | LLM local |
| CUDA toolkit | 11.8+ | Aceleración GPU para Whisper |
| Expo CLI | Latest | `npm install -g expo-cli` |

## Inicio rápido
- Si quedan instancias residuales de despliegues anteriores ```./scripts/kill-processes.ps1``` debería arreglarlo.
### 1. Base de datos

```bash
# Opción A: MariaDB local ya instalado
mysql -u root -p < backend/init_db.sql
mysql -u root -p < backend/fix_auth.sql   # crea usuario tfg_app (necesario en MariaDB 12+)

# Opción B: Docker
docker run -d --name mariadb \
  -e MARIADB_ROOT_PASSWORD=rootpass \
  -e MARIADB_DATABASE=tfg_demencia \
  -p 3306:3306 \
  mariadb:11
# Luego inicializar esquema:
docker exec -i mariadb mysql -u root -prootpass < backend/init_db.sql
```

### 2. Ollama (LLM local)

```bash
# Instalar Ollama: https://ollama.ai
# Descargar un modelo (phi3:mini viene por defecto, openhermes es buena alternativa)
ollama pull phi3:mini

# Verificar que funciona
ollama run phi3:mini "Hola, ¿cómo estás?"
# Escribe /bye para salir

# Ollama se ejecuta por defecto en http://localhost:11434
```

### 3. Backend

```powershell
.\scripts\run-backend.ps1
```

Este script activa el entorno virtual (`.venv`), configura las variables de entorno necesarias y lanza el servidor con `uvicorn --reload`. El backend estará en `http://localhost:8000`. Documentación interactiva en `http://localhost:8000/docs`.

### 4. Frontend (App móvil)

```powershell
# Primero: detecta tu IP local y genera el .env del frontend
.\scripts\update-frontend-env.ps1

# Después: lanza la app (instala dependencias automáticamente la primera vez)
.\scripts\run-frontend.ps1
```

Escanea el QR con Expo Go en tu móvil para probar.

### Scripts disponibles

| Script | Qué hace |
|---|---|
| `scripts\run-backend.ps1` | Activa `.venv`, configura env vars, lanza uvicorn |
| `scripts\run-frontend.ps1` | Instala deps si faltan, lanza `expo start` |
| `scripts\update-frontend-env.ps1` | Detecta tu IP LAN y escribe `frontend/app/.env` |
| `scripts\get-ip.ps1` | Muestra tus IPs IPv4 activas |
| `scripts\kill-processes.ps1` | Mata los procesos de frontend y backend |

## Flujo de prueba completo

1. **Registrar un cuidador**: Abre la app → "Regístrate" → selecciona "Responsable" → introduce datos.
2. **Registrar un paciente**: Cierra sesión → "Regístrate" → selecciona "Paciente" → introduce el email del cuidador.
3. **Configurar contexto**: Inicia sesión como cuidador → pulsa el paciente → edita frases gatillo y perfil → guarda.
4. **Probar detección**: Inicia sesión como paciente → "Activar escucha" → di una frase gatillo como "ayuda" o "no sé dónde estoy".
5. **Ver alerta**: Inicia sesión como cuidador → la alerta aparece en la lista → púlsala para aceptarla.

## Configuración Tailscale (para acceso remoto)

1. Instala Tailscale en el PC con el backend y en los móviles.
2. Todos deben estar en el mismo tailnet (misma cuenta).
3. Usa la IP de Tailscale del PC como `EXPO_PUBLIC_SERVER_URL`.

```bash
# Ver tu IP de Tailscale
tailscale ip -4
# Ejemplo resultado: 100.64.0.1
# Entonces: EXPO_PUBLIC_SERVER_URL=http://100.64.0.1:8000
```

## Estructura del proyecto

```
TFG-DEMENCIA/
├── backend/
│   ├── init_db.sql              # Esquema de base de datos
│   ├── requirements.txt         # Dependencias Python
│   └── src/
│       ├── server.py            # Entry point FastAPI
│       ├── config.py            # Configuración (env vars)
│       ├── database.py          # Conexión SQLAlchemy
│       ├── auth.py              # JWT + password hashing
│       ├── models/              # ORM models (SQLAlchemy)
│       ├── schemas/             # Pydantic request/response
│       ├── routes/              # API endpoints
│       └── services/            # Lógica de negocio
│           ├── stt_service.py   # Transcripción Whisper
│           ├── episode_detector.py  # Detección de episodios
│           └── llm/             # Strategy pattern para LLM
│               ├── base.py      # Interfaz abstracta
│               ├── ollama_provider.py
│               ├── openai_provider.py
│               └── factory.py   # Factory method
├── frontend/
│   └── app/                     # App principal (Expo/RN)
│       ├── App.js               # Root con routing por rol
│       └── src/
│           ├── screens/         # Pantallas
│           └── services/        # API client
├── scripts/                     # Scripts de utilidad
│   ├── run-backend.ps1          # Lanzar backend
│   ├── run-frontend.ps1         # Lanzar frontend
│   ├── update-frontend-env.ps1  # Auto-detectar IP
│   └── get-ip.ps1               # Ver IPs
└── deep-research-report.md      # Documento de investigación
```

## Variables de entorno del backend

| Variable | Default | Descripción |
|---|---|---|
| `DB_HOST` | `127.0.0.1` | Host de MariaDB |
| `DB_PORT` | `3306` | Puerto de MariaDB |
| `DB_NAME` | `tfg_demencia` | Nombre de la base de datos |
| `DB_USER` | `tfg_app` | Usuario de la BD |
| `DB_PASSWORD` | `tfg_pass_2024` | Contraseña de la BD |
| `JWT_SECRET` | `change-me-in-production` | Clave secreta para JWT |
| `JWT_EXPIRE_MINUTES` | `1440` | Expiración de tokens (24h) |
| `STT_MODEL` | `base` | Modelo Whisper (`base`, `small`, `medium`, `large-v3-turbo`) |
| `STT_DEVICE` | `cuda` | Dispositivo STT (`cuda` o `cpu`) |
| `LLM_PROVIDER` | `ollama` | Proveedor LLM (`ollama` o `openai`) |
| `LLM_MODEL` | `phi3:mini` | Modelo a usar |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | URL de Ollama |
| `OPENAI_API_KEY` | (vacío) | API key para proveedor OpenAI |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Base URL compatible OpenAI |

## API Reference

Documentación interactiva completa en `/docs` (Swagger UI) cuando el backend está corriendo.

### Endpoints principales

| Método | Ruta | Rol | Descripción |
|---|---|---|---|
| POST | `/auth/register` | Público | Registro de usuario |
| POST | `/auth/login` | Público | Login → JWT |
| GET | `/patients/` | Cuidador | Listar pacientes |
| GET | `/patients/{id}/context` | Cuidador | Obtener contexto |
| PUT | `/patients/{id}/context` | Cuidador | Actualizar contexto |
| POST | `/audio/chunk` | Paciente | Enviar audio → análisis |
| GET | `/alerts/` | Cuidador | Listar alertas |
| POST | `/alerts/{id}/ack` | Cuidador | Aceptar alerta |
| GET | `/health` | Público | Estado del sistema |

## Decisiones de diseño

### ¿Por qué una sola app con dos roles en vez de dos apps separadas?
- Reduce la duplicación de código (servicios, autenticación, navegación).
- El mismo APK se distribuye a pacientes y cuidadores.
- El rol determina la interfaz tras el login.

### ¿Por qué Strategy pattern para LLM?
- Permite cambiar entre Ollama (local) y OpenAI (cloud) con solo cambiar una variable de entorno.
- Demuestra escalabilidad: si el proyecto se desplegara en producción, bastaría con añadir un nuevo provider.
- Facilita testing: se podría crear un `MockProvider` para pruebas unitarias.

### ¿Por qué detección en dos fases (reglas + LLM)?
- Las reglas regex son instantáneas y deterministas - responden rápido ante frases conocidas.
- El LLM aporta comprensión contextual para frases no previstas.
- Si el LLM falla o tarda, las reglas siguen funcionando como fallback.

### ¿Por qué MariaDB con campos JSON?
- Combina la solidez de las tablas relacionales (usuarios, alertas, integridad referencial) con la flexibilidad del JSON para el contexto del paciente.
- El contexto cambia frecuentemente en estructura; JSON evita migraciones constantes.

## Cambiar el modelo LLM

```bash
# Usar openhermes en vez de phi3:mini
ollama pull openhermes
$env:LLM_MODEL="openhermes"

# Usar API de OpenAI (o compatible)
$env:LLM_PROVIDER="openai"
$env:OPENAI_API_KEY="sk-..."
$env:LLM_MODEL="gpt-4o-mini"
```

## Troubleshooting

| Problema | Solución |
|---|---|
| `CUDA out of memory` al cargar Whisper | Usa un modelo más pequeño: `STT_MODEL=base` o `STT_MODEL=small` |
| `Connection refused` en la app | Verifica que usas la IP correcta (no `localhost` desde el móvil) |
| Ollama no responde | Verifica que está corriendo: `ollama list` |
| Error de CORS | El backend ya tiene CORS abierto para desarrollo |
| MariaDB connection error | Verifica que el servicio está corriendo y las credenciales son correctas |tonomy
