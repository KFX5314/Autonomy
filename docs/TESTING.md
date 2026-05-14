# Estrategia de pruebas

La suite de backend separa dos tipos de validacion:

- **Tests automaticos reproducibles**: autenticacion, permisos, reglas de episodios, parsers, gestion de alertas y endpoint de audio con STT/diarizacion/LLM mockeados.
- **Pruebas experimentales locales**: STT real, diarizacion real, LLM local y tiempos de procesamiento. No forman parte de la suite por defecto porque dependen de modelos, hardware y audios privados.

## Preparar MariaDB de test

Los tests de integracion usan una base separada llamada `tfg_demencia_test`. Nunca deben ejecutarse contra `tfg_demencia`.

Desde la raiz del proyecto:

```powershell
mariadb -u root -p < backend/init_test_db.sql
```

Si tu instalacion de MariaDB conserva el alias historico `mysql`, el comando equivalente tambien funcionara con `mysql -u root -p`.

Por defecto los tests usan:

```env
TEST_DB_HOST=127.0.0.1
TEST_DB_PORT=3306
TEST_DB_NAME=tfg_demencia_test
TEST_DB_USER=tfg_app
TEST_DB_PASSWORD=tfg_pass_2024
```

`TEST_DB_NAME` debe terminar en `_test`; si no, la suite aborta antes de tocar la base de datos.

## Ejecutar tests

Instalar dependencias de desarrollo:

```powershell
cd backend
pip install -r requirements.txt -r requirements-dev.txt
```

Ejecutar la suite normal:

```powershell
python -m pytest
```

La cache interna de pytest esta desactivada para evitar errores de permisos en Windows. Los tests que necesitan archivos temporales persistentes usan `backend/.pytest_runtime/`, ignorado por Git.

Si el equipo no tiene GPU dedicada activa, o CUDA no esta disponible, fuerza Whisper en CPU antes de ejecutar tests con audio real:

```powershell
$env:STT_DEVICE="cpu"
```

Ejecutar solo tests de integracion:

```powershell
python -m pytest -m integration
```

Ejecutar solo tests unitarios rapidos:

```powershell
python -m pytest -m "not integration"
```

Ejecutar validacion local con audios reales:

```powershell
python -m pytest -m audio_real
```

Ejecutar el flujo HTTP real de memoria con servidor externo:

```powershell
$env:TFG_RUN_SERVER_E2E="1"
python -m pytest -m server_e2e tests/test_memory_server_e2e_optional.py
```

Ese test arranca `scripts/run-backend-e2e.ps1` contra `tfg_demencia_test`, registra cuidador/paciente por HTTP, rellena STM y Journal con datos mock en la base de test, y consulta los endpoints reales. Para no depender de modelos en una prueba de memoria, ese launcher de test activa `TFG_SKIP_MODEL_WARMUP=1` y `TFG_SKIP_HEALTH_LLM=1`, y no llama endpoints que necesiten inferencia LLM real.

Por defecto el test busca audios privados en:

```text
backend/tests/fixtures/private_audio/
```

Tambien puedes usar otra carpeta:

```powershell
$env:TFG_AUDIO_FIXTURES_DIR="C:\ruta\a\audios_privados"
python -m pytest -m audio_real
```

## Audio

Los tests automaticos no suben audios reales al repositorio. El endpoint `/audio/chunk` se prueba con multipart dummy y servicios mockeados para validar el flujo HTTP, persistencia y creacion de alertas sin arrancar Whisper, SpeechBrain ni Ollama.

Los audios reales usados para validar STT/diarizacion deben guardarse fuera de Git, por ejemplo:

```text
backend/tests/fixtures/private_audio/
```

Esa carpeta y las extensiones de audio comunes estan ignoradas en `.gitignore`. Si la carpeta esta vacia, el test se salta con un mensaje claro. Graba un audio corto propio y guardalo ahi como `.wav`, `.m4a`, `.mp3` o `.aac` para ejecutar la validacion real.

Para la memoria del proyecto, las pruebas reales de audio deben presentarse como validacion experimental local: indicar entorno, numero de ejecuciones, resultado observado y limitaciones. No deben usarse voces de pacientes reales ni audios con datos personales.

## KPIs recomendadas

| KPI | Metodo | Umbral |
|---|---|---|
| Registro/login y roles | Tests de integracion | 100% casos definidos |
| Permisos cuidador/paciente | Tests de integracion | 100% casos definidos |
| Frases/regex de alerta | Tests unitarios | 100% casos definidos |
| Pipeline de alerta mockeado | Test de integracion | Correcto |
| Flujo HTTP de STM/Journal | Test opcional `server_e2e` | Correcto |
| Overhead con STM/Journal llenos | Tests `performance` mockeados, sin Whisper/Ollama | <1 s recomendado |
| STT real | Prueba experimental local | >=80% palabras clave |
| Diarizacion real | Prueba experimental local | Reportar acierto en casos definidos |
| Tiempo total de chunk real | Prueba experimental local con audio + LLM reales | <20 s recomendado |
