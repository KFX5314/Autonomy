# Estrategia de pruebas

La suite de backend separa dos tipos de validación:

- **Tests automáticos reproducibles**: autenticación, permisos, reglas de episodios, parsers, gestión de alertas y endpoint de audio con STT/diarización/LLM mockeados.
- **Pruebas experimentales locales**: STT real, diarización real, LLM local y tiempos de procesamiento. No forman parte de la suite por defecto porque dependen de modelos, hardware y audios privados.

## Preparar MariaDB de test

Los tests de integración usan una base separada llamada `tfg_demencia_test`. Nunca deben ejecutarse contra `tfg_demencia`.

Desde la raíz del proyecto:

```powershell
mariadb -u root -p < backend/init_test_db.sql
```

Si tu instalación de MariaDB conserva el alias histórico `mysql`, el comando
equivalente también funcionará con `mysql -u root -p`.

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

Ejecutar sólo tests de integración:

```powershell
python -m pytest -m integration
```

Ejecutar sólo tests unitarios rápidos:

```powershell
python -m pytest -m "not integration"
```

Ejecutar validación local con audios reales:

```powershell
$env:TFG_AUDIO_FIXTURES_DIR="C:\ruta\a\audios_privados"
python -m pytest -m audio_real
```

## Audio

Los tests automáticos no suben audios reales al repositorio. El endpoint `/audio/chunk` se prueba con multipart dummy y servicios mockeados para validar el flujo HTTP, persistencia y creación de alertas sin arrancar Whisper, SpeechBrain ni Ollama.

Los audios reales usados para validar STT/diarización deben guardarse fuera de Git, por ejemplo:

```text
backend/tests/local_audio/
```

Esa carpeta y las extensiones de audio comunes están ignoradas en `.gitignore`.

Para la memoria del proyecto, las pruebas reales de audio deben presentarse como validación experimental local: indicar entorno, número de ejecuciones, resultado observado y limitaciones. No deben usarse voces de pacientes reales ni audios con datos personales.

## KPIs recomendadas

| KPI | Método | Umbral |
|---|---|---|
| Registro/login y roles | Tests de integración | 100% casos definidos |
| Permisos cuidador/paciente | Tests de integración | 100% casos definidos |
| Frases/regex de alerta | Tests unitarios | 100% casos definidos |
| Pipeline de alerta mockeado | Test de integración | Correcto |
| STT real | Prueba experimental local | >=80% palabras clave |
| Diarización real | Prueba experimental local | Reportar acierto en casos definidos |
| Tiempo total de chunk real | Prueba experimental local | <20 s recomendado |
