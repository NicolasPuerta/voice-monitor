# Ubuntu Voice Monitor

Aplicación Python para Ubuntu que observa el comportamiento del sistema
operativo, envía información relevante a Gemini para su análisis y
reproduce por audio el análisis generado.

```
Ubuntu → Python Monitor → System Context → Gemini → Analysis → Audio → Ubuntu Speakers
```

## Principios

- Sin entrada de voz ni micrófono; no hay conversación con el usuario.
- Python obtiene la información del sistema.
- Gemini solo analiza la información recibida: no ejecuta comandos ni
  modifica el sistema.

## Estado

Hasta el momento se ha implementado lo siguiente:

- **Estructura del Proyecto y Configuración:** Pytest, flake8, mypy, pylint (MR 01).
- **Configuración y Modelos de Dominio:** Configuración centralizada con Pydantic Settings y modelos de dominio inmutables (MR 02).
- **Process Collector:** Observación de procesos de Linux (pid, stado, CPU, memoria, cmdline sanitizado) utilizando psutil de forma segura (MR 03).
- **System Metrics Collectors:** Métricas del sistema, PSI desde /proc/pressure/ y estado energético desde /sys/class/power_supply/ (MR 04).
- **Application Grouping and Context:** SystemContextBuilder para combinar métricas con agrupación lógica heurística basada en cgroups y árbol de procesos (MR 05).
- **Event Prioritization and Flow Control:** ScoringEngine determinista, ventanas de coalescencia (EventGrouper), PriorityQueue (TTL) y prevencion de saturación sonora con FlowController (MR 07).
- **Persistence and Process Knowledge Base:** Persistencia SQLite (WAL) y base de conocimiento versionada sobre procesos de Linux comunes (MR 08).

Aún no están implementados la detección de anomalías complejas, la integración final con Gemini ni el TTS.

## Estructura

```
app/          Código fuente (punto de entrada: app/main.py)
app/core/     Configuración (config.py) y logging (logging.py)
app/domain/   Modelos y enums del dominio (independientes de psutil)
tests/        Pruebas con pytest
scripts/      Utilidades de desarrollo
```

## Configuración

Se lee de variables de entorno o de un archivo `.env` (ver `.env.example`);
el entorno tiene prioridad. Las variables ausentes o vacías usan su valor por
defecto y los valores inválidos detienen el arranque con un error claro.

| Variable                       | Defecto            | Descripción                                   |
|--------------------------------|--------------------|-----------------------------------------------|
| `APP_ENV`                      | `development`      | `development`, `test` o `production`          |
| `LOG_LEVEL`                    | `INFO`             | DEBUG, INFO, WARNING, ERROR, CRITICAL         |
| `COLLECTOR_INTERVAL_S`         | `5`                | Segundos entre lecturas (0.5 – 3600)          |
| `COLLECTOR_BATTERY_INTERVAL_S` | `15`               | Igual, en batería (debe ser ≥ el anterior)    |
| `COLLECTOR_ADAPTIVE`           | `true`             | Adapta el intervalo a la actividad            |
| `GEMINI_ENABLED`               | `false`            | Si es `true`, `GEMINI_API_KEY` es obligatoria |
| `GEMINI_MODEL`                 | `gemini-2.5-flash` | Modelo de Gemini                              |
| `GEMINI_API_KEY`               | *(vacía)*          | Nunca en el código ni en logs                 |
| `NARRATION_VERBOSITY`          | `normal`           | `minimal`, `normal` o `verbose`               |
| `NARRATION_MIN_GAP_S`          | `10`               | Segundos mínimos entre narraciones            |
| `NARRATION_MAX_BURST`          | `3`                | Narraciones seguidas antes de pausar          |
| `NARRATION_EVENT_TTL_S`        | `60`               | Vigencia de un evento (≥ `MIN_GAP_S`)         |
| `PRIVACY_REDACT_HOME`          | `true`             | Oculta el directorio personal                 |
| `STORAGE_DB_PATH`              | `~/.local/share/ubuntu-voice-monitor/events.db` | Ruta de la base local |
| `DND_ENABLED`                  | `false`            | No Molestar: no se narra ningún evento        |

```python
from pathlib import Path

from app.core import Settings, configure_logging

settings = Settings.load(Path(".env"))
configure_logging(settings.app.log_level)
```

Los logs incluyen timestamp y nivel:
`2026-10-06 20:56:44 | INFO     | app.main | mensaje`.


## Requisitos

- Python 3.10 o superior

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env               # Windows: copy .env.example .env
```

## Uso

```bash
python -m app
```

## Calidad de código

```bash
pytest
flake8 app tests
mypy
pylint app tests
```

O todo junto: `bash scripts/check.sh`.

## Convenciones

- Código fuente (variables, clases, funciones) en inglés.
- Docstrings en español (estilo Google).
- Comentarios técnicos preferiblemente en inglés.
- Mensajes al usuario pueden estar en español.
- Type hints obligatorios; longitud máxima de línea: 90.

## Audio y Reproducción (WSL vs Ubuntu Nativo)
El sistema reproduce el análisis de Gemini mediante altavoces, operando en un hilo independiente para evitar bloqueos (AudioQueueManager).
Implementa fallback automático (Gemini Audio -> Piper -> espeak-ng) y caché en memoria para no regenerar el mismo reporte repetidas veces.

### Diferencias de Entorno
- **Ubuntu Nativo:** Utiliza la configuración de audio predeterminada (ALSA, PulseAudio, PipeWire). Herramientas como play o paplay funcionan _out-of-the-box_ sin lag notable.
- **WSL (Windows Subsystem for Linux):** Requiere **WSLg** para soportar el puente de PulseAudio automáticamente hacia el host de Windows. Si el audio no se escucha en WSL:
  1. Verifica que WSLg esté habilitado.
  2. Opcionalmente redirige el output de audio hacia el ejecutable nativo de Windows (e.g. usando powershell o un servidor PulseAudio en Windows).

## Ejecución de Demo End-to-End
Puedes probar la arquitectura completa sin integrarla todavía en el main.py usando el script de demostración incluido:
`ash
python scripts/demo_pipeline.py
`
Este comando encenderá el NarrationPipeline, usará Gemini y generará voz sintética usando las prioridades configuradas. Para detenerlo, usa Ctrl+C.
