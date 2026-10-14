# Ubuntu Voice Monitor

Aplicación Python para Ubuntu que observa el comportamiento del sistema operativo, analiza eventos relevantes mediante Gemini y narra los hallazgos al usuario a través de audio.

```
Ubuntu (procfs/sysfs/psutil) → System Context → Event Detector → Scoring & Flow Control → Gemini Analysis → Audio Player → Parlantes
```

## Principios

- **Estrictamente de solo lectura:** No ejecuta comandos ni altera el estado del sistema operativo.
- **Sin entrada de voz ni micrófono:** No hay escucha ni conversación interactiva; el agente únicamente narra reportes.
- **Privacidad primero:** Rutas de usuario (`$HOME`), tokens, credenciales y variables de entorno se enmascaran localmente antes de enviar datos a la nube.
- **No bloqueante:** La recolección de métricas nunca espera por respuestas de red (Gemini) ni por la reproducción de audio.

---

## Estado del Proyecto

Se han completado los módulos correspondientes a los **MR 01 al MR 12**:

- **MR 01 - Estructura y Herramientas:** Base con `pytest`, `flake8`, `mypy`, `pylint`.
- **MR 02 - Configuración y Dominio:** Configuración centralizada (`Pydantic Settings`), inmutabilidad y validación de tipos.
- **MR 03 - Process Collector:** Observación de procesos de Linux (`pid`, `estado`, `CPU`, `memoria`, `cmdline` sanitizado) con `psutil`.
- **MR 04 - System Metrics Collectors:** Métricas de CPU, Memoria (`MemAvailable`), Swap, PSI (`/proc/pressure/`) y estado energético (`/sys/class/power_supply/`) con `SourceHealthManager`.
- **MR 05 - Application Grouping & System Context:** `SystemContextBuilder` para agrupar árboles de subprocesos por aplicación y `cgroups` sin inventar identidades.
- **MR 07 - Event Prioritization & Flow Control:** `ScoringEngine` explicable y determinista, coalescencia de 3 s (`EventGrouper`), cola con TTL de 30 s (`PriorityQueue`) y control de saturación por token bucket (`FlowController`) con soporte de preemption para eventos críticos.
- **MR 08 - Persistencia y Knowledge Base:** Base de datos SQLite asíncrona (`WAL`), repositorio de eventos y base de conocimiento de procesos con resolución curada y heurística.
- **MR 09 - Gemini Integration Foundation:** `PrivacySanitizer` (redacción de secretos, JWT, AWS keys, URLs con auth), `GeminiContextBuilder`, y `GeminiClient` con reintentos y `CircuitBreaker`.
- **MR 10 - Gemini Analysis Agent:** `AnalysisAgent` con modelo estructurado Pydantic (`AnalysisResult`), prompts versionados en español para lenguaje no técnico.
- **MR 11 - Audio Output:** `AudioQueueManager` asíncrono con cancelación/interrupción, caché SHA-256 y cascada de fallbacks (`Gemini Audio` → `Piper TTS` → `espeak-ng`).
- **MR 12 - End-to-End Narration Pipeline:** Integración completa en `NarrationPipeline`, detector basado en reglas y demostración funcional CLI.

---

## Requisitos Previos

- **Sistema Operativo:** Ubuntu 22.04 / 24.04 nativo o WSL2 (con **WSLg** para audio).
- **Python:** 3.10 o superior.
- **Herramientas de audio (opcional según el motor):**
  - Para fallback ligero: `sudo apt install espeak-ng alsa-utils`
  - Para Piper (neural TTS offline): binario `piper` y modelo `.onnx`.
  - Para reproducción general: `aplay` (incluido en `alsa-utils`), `paplay` o `ffplay` (`ffmpeg`).

---

## Guía de Instalación y Ejecución desde Cero

### 1. Clonar o ingresar al repositorio

```bash
cd voice-monitor
```

### 2. Crear y activar el entorno virtual

En Ubuntu / Linux / WSL:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

*(En Windows PowerShell: `python -m venv .venv` y `.venv\Scripts\Activate.ps1`)*

### 3. Instalar dependencias

```bash
pip install --upgrade pip
pip install -e ".[dev]"
```

### 4. Configurar las variables de entorno

Copia la plantilla `.env.example`:
```bash
cp .env.example .env
```

Edita `.env` con tus preferencias. Para habilitar Gemini con análisis en la nube:
```ini
GEMINI_ENABLED=true
GEMINI_API_KEY=tu_api_key_de_google_ai_studio
GEMINI_MODEL=gemini-2.5-flash
```

Si deseas usar **Piper TTS** para voz neuronal offline, especifica la ruta de tu modelo:
```ini
NARRATION_PIPER_MODEL_PATH=/ruta/al/modelo/es_ES-enrique-medium.onnx
```

---

## Cómo Ejecutar

### Opción A: Demostración del Pipeline Completo (End-to-End)

Ejecuta el pipeline completo con recolección, detección de eventos, puntuación, análisis con Gemini y salida por voz:

```bash
python scripts/demo_pipeline.py
```

- Se ejecutará en un bucle continuo de monitoreo.
- Para detenerlo, presiona `Ctrl + C`.
- Si deseas ejecutarlo durante un número exacto de iteraciones/segundos (por ejemplo, 10 segundos):
  ```bash
  python scripts/demo_pipeline.py --iterations 10
  ```

### Opción B: Prueba Aislada de Análisis de Gemini

Para verificar únicamente la conexión con Gemini y la estructura del reporte sin activar recolectores:

```bash
python scripts/test_analysis.py
```

### Opción C: Ejecución de Pruebas Automatizadas y Calidad

Para correr la suite de tests unitarios y de integración:
```bash
pytest
```

Para verificar estilo y tipos:
```bash
flake8 app tests scripts
mypy app tests scripts
```

---

## Tabla de Configuración (`.env`)

| Variable                       | Defecto                                        | Descripción                                    |
|--------------------------------|------------------------------------------------|------------------------------------------------|
| `APP_ENV`                      | `development`                                  | `development`, `test` o `production`           |
| `LOG_LEVEL`                    | `INFO`                                         | DEBUG, INFO, WARNING, ERROR, CRITICAL          |
| `COLLECTOR_INTERVAL_S`         | `5.0`                                          | Segundos entre lecturas de métricas            |
| `COLLECTOR_BATTERY_INTERVAL_S` | `15.0`                                         | Segundos entre lecturas funcionando en batería |
| `COLLECTOR_ADAPTIVE`           | `true`                                         | Adapta el intervalo según carga del sistema    |
| `GEMINI_ENABLED`               | `false`                                        | Si es `true`, requiere `GEMINI_API_KEY`        |
| `GEMINI_MODEL`                 | `gemini-2.5-flash`                             | Modelo de Gemini para el análisis              |
| `GEMINI_API_KEY`               | *(vacía)*                                      | Clave privada (nunca se muestra en logs)       |
| `NARRATION_VERBOSITY`          | `normal`                                       | `minimal`, `normal` o `verbose`                |
| `NARRATION_MIN_GAP_S`          | `10.0`                                         | Tiempo mínimo entre dos narraciones            |
| `NARRATION_MAX_BURST`          | `3`                                            | Ráfaga máxima de narraciones permitida         |
| `NARRATION_EVENT_TTL_S`        | `60.0`                                         | Segundos de vigencia antes de expirar evento   |
| `NARRATION_PIPER_MODEL_PATH`   | *(vacía)*                                      | Ruta al modelo `.onnx` de Piper TTS (opcional) |
| `PRIVACY_REDACT_HOME`          | `true`                                         | Reemplaza `$HOME` por `~` en textos            |
| `STORAGE_DB_PATH`              | `~/.local/share/ubuntu-voice-monitor/events.db`| Ruta del archivo SQLite                        |
| `DND_ENABLED`                  | `false`                                        | Modo No Molestar (silencia toda narración)     |

---

## Consideraciones de Audio (WSL vs Ubuntu Nativo)

- **Ubuntu Nativo:** Utiliza PulseAudio, PipeWire o ALSA directamente. `aplay` (de `alsa-utils`) funciona de forma nativa sin configuración adicional.
- **WSL (Windows Subsystem for Linux):** Requiere **WSLg** (presente por defecto en Windows 11 o Windows 10 actualizado) para canalizar el audio de PulseAudio hacia los altavoces de Windows. Si no escuchas sonido en WSL:
  1. Verifica que el servidor de audio responda: `aplay /usr/share/sounds/alsa/Front_Center.wav`.
  2. Asegúrate de tener instalado `alsa-utils` y `espeak-ng`.
