# Guía Completa de Configuración y Variables de Entorno

**Ubuntu Voice Monitor** utiliza un sistema de configuración centralizado, tipado e inmutable gestionado mediante **Pydantic Settings** (`app.core.config.Settings`).

---

## 1. Orden de Precedencia de la Configuración

La configuración se evalúa según la siguiente jerarquía estricta (el nivel superior sobrescribe a los inferiores):

```
1. Argumentos de Línea de Comandos (CLI) (ej. --no-audio, --debug, --verbosity)
      ▲
2. Variables de Entorno del Sistema (ej. export GEMINI_ENABLED=true)
      ▲
3. Archivo de Entorno (.env o ruta especificada con --config)
      ▲
4. Valores Predeterminados del Código (definidos en las clases de Settings)
```

---

## 2. Tabla Maestra de Variables de Entorno

| Variable | Tipo / Valores | Obligatoria | Valor por Defecto | Descripción |
|:---|:---:|:---:|:---:|:---|
| **`APP_ENV`** | `development`, `test`, `production` | No | `development` | Entorno de ejecución de la aplicación. |
| **`LOG_LEVEL`** | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | No | `INFO` | Nivel mínimo de severidad para emisión de logs en consola y archivo. |
| **`COLLECTOR_INTERVAL_S`** | `float` (0.5 a 3600.0) | No | `5.0` | Intervalo en segundos entre ciclos de recolección conectado a corriente. |
| **`COLLECTOR_BATTERY_INTERVAL_S`** | `float` ($\ge$ `interval_s`) | No | `15.0` | Intervalo en segundos durante operación con batería para ahorrar energía. |
| **`COLLECTOR_ADAPTIVE`** | `bool` (`true`/`false`) | No | `true` | Adapta la frecuencia de sondeo dinámicamente según la actividad del sistema. |
| **`NARRATION_VERBOSITY`** | `minimal`, `normal`, `verbose` | No | `normal` | Nivel de detalle de las explicaciones generadas y los registros en pantalla. |
| **`NARRATION_MIN_GAP_S`** | `float` ($\ge 0$) | No | `10.0` | Tiempo mínimo en segundos de silencio entre dos narraciones consecutivas. |
| **`NARRATION_MAX_BURST`** | `int` ($\ge 1$) | No | `3` | Límite máximo de eventos narrados consecutivamente (token bucket) antes de forzar pausa. |
| **`NARRATION_EVENT_TTL_S`** | `float` ($\ge$ `min_gap_s`) | No | `60.0` | Tiempo de vida de un evento en cola. Se descarta si expira antes de poder hablar. |
| **`NARRATION_PIPER_MODEL_PATH`** | `string` (ruta a archivo) | No | `None` | Ruta absoluta al modelo `.onnx` de Piper TTS (voz neuronal primordial offline). |
| **`GEMINI_ENABLED`** | `bool` (`true`/`false`) | No | `false` | Habilita el análisis cognitivo mediante la API en la nube de Google Gemini. |
| **`GEMINI_MODEL`** | `string` | No | `gemini-2.5-flash` | Modelo de Gemini utilizado para analizar el contexto del sistema. |
| **`GEMINI_API_KEY`** | `string` (secreto) | **Sí** (si Gemini habilitado) | `None` | Clave de acceso a la API de Google Gemini (nunca se muestra en logs). |
| **`STORAGE_DB_PATH`** | `string` (ruta) | No | `~/.local/share/ubuntu-voice-monitor/events.db` | Ruta del archivo de base de datos SQLite donde se persisten eventos y sesiones. |
| **`PRIVACY_REDACT_HOME`** | `bool` (`true`/`false`) | No | `true` | Enmascara automáticamente la ruta del directorio home (`/home/<user>`) por `~`. |
| **`DND_ENABLED`** | `bool` (`true`/`false`) | No | `false` | Activa el modo No Molestar manualmente desde configuración (silencia altavoz). |

---

## 3. Obtención y Configuración de Credenciales de Gemini

Para habilitar el análisis inteligente con Google Gemini:

1. Ingresa a la consola de [Google AI Studio](https://aistudio.google.com/apikey).
2. Genera una API Key para tu proyecto.
3. Configura la clave en tu archivo `.env`:
   ```bash
   GEMINI_ENABLED=true
   GEMINI_API_KEY=AIzaSy...TuClaveAqui...
   GEMINI_MODEL=gemini-2.5-flash
   ```
4. **Seguridad:** El archivo `.env` está expresamente excluido en el `.gitignore`. Nunca realices commits de credenciales o claves privadas al repositorio.

---

## 4. Configuración del Motor de Voz Primordial (Piper TTS)

El motor primordial del monitor es **Piper TTS**, un sintetizador neuronal de voz offline ultra-rápido:

1. Descarga el modelo de voz en español y su archivo `.json` complementario:
   ```bash
   mkdir -p ~/.local/share/piper
   cd ~/.local/share/piper
   wget https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx
   wget https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx.json
   ```
2. Indica la ruta del modelo en tu `.env`:
   ```ini
   NARRATION_PIPER_MODEL_PATH=/home/usuario/.local/share/piper/es_ES-davefx-medium.onnx
   ```
3. Si el binario `piper` no está disponible en `$PATH` o no se define un modelo, el monitor conmuta automáticamente a **`espeak-ng`** como respaldo local sin interrumpir la ejecución.
