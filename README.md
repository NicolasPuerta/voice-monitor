# Ubuntu Voice Monitor (Narrador Linux)

[![CI Pipeline](https://img.shields.io/badge/CI-Passing-brightgreen.svg)](#12-tests-y-calidad)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![Tested on Ubuntu & Debian](https://img.shields.io/badge/OS-Ubuntu%2022.04%20%7C%2024.04%20%7C%20Debian%2012-orange.svg)](#3-requisitos-previos)
[![Code Style: Flake8](https://img.shields.io/badge/code%20style-flake8%20(<=90)-black.svg)](#12-tests-y-calidad)
[![Type Checked: Mypy Strict](https://img.shields.io/badge/mypy-strict%20(0%20errors)-blueviolet.svg)](#12-tests-y-calidad)
[![Coverage: >84%](https://img.shields.io/badge/coverage-%3E84%25-brightgreen.svg)](#12-tests-y-calidad)

**Ubuntu Voice Monitor** es un agente observacional para sistemas operativos Linux que monitorea en segundo plano el consumo de recursos, la salud de los procesos y eventos del kernel. Cuando ocurre un comportamiento relevante o anómalo (saturación de CPU, presión extrema de memoria, procesos zombi, reinicios en bucle de systemd u OOM Killer), genera una explicación concisa y accesible mediante Google Gemini (o síntesis de reglas local) y la **narra al usuario mediante voz sintetizada**, permitiéndole mantenerse al tanto de la salud de su máquina sin necesidad de monitores de terminal permanentemente abiertos.

---

## Índice General

1. [Descripción del Proyecto](#1-descripción-del-proyecto)
2. [Estado Actual y Roadmap](#2-estado-actual-y-roadmap)
3. [Requisitos Previos](#3-requisitos-previos)
4. [Instalación Paso a Paso](#4-instalación-paso-a-paso)
5. [Configuración y Variables de Entorno](#5-configuración-y-variables-de-entorno)
6. [Cómo Ejecutar el Proyecto](#6-cómo-ejecutar-el-proyecto)
7. [Configuración y Funcionamiento de Gemini](#7-configuración-y-funcionamiento-de-gemini)
8. [Subsistema de Audio y Motores de Voz](#8-subsistema-de-audio-y-motores-de-voz)
9. [Arquitectura y Estructura del Código](#9-arquitectura-y-estructura-del-código)
10. [Base de Datos y Almacenamiento](#10-base-de-datos-y-almacenamiento)
11. [Logs y Solución de Problemas](#11-logs-y-solución-de-problemas)
12. [Tests y Calidad](#12-tests-y-calidad)
13. [Seguridad y Privacidad](#13-seguridad-y-privacidad)
14. [Servicio systemd de Usuario](#14-servicio-systemd-de-usuario)
15. [Actualización, Desinstalación y Mantenimiento](#15-actualización-desinstalación-y-mantenimiento)
16. [Información para Desarrolladores](#16-información-para-desarrolladores)
17. [Documentación Complementaria](#17-documentación-complementaria)

---

## 1. Descripción del Proyecto

### 1.1 Qué es y qué problema resuelve
En entornos de desarrollo y servidores Linux, el usuario suele enterarse de problemas de rendimiento (bloqueos por E/S, agotamiento de RAM por navegadores o compiladores, bucles infinitos en servicios) cuando el sistema ya se ha congelado o el OOM Killer ha terminado procesos arbitrariamente. 

**Ubuntu Voice Monitor** resuelve este problema actuando como un copiloto observador auditivo: vigila las señales métricas del kernel y, en lugar de generar alertas visuales invasivas o requerir que el usuario mantenga abierto `htop`, narra de forma oportuna y no técnica qué proceso o subsistema está exigiendo atención.

### 1.2 Responsabilidades: Python vs Gemini
- **Responsabilidad de Python (El Núcleo Operativo):**
  - Muestreo periódico no invasivo de métricas de Linux (`/proc`, `/sys`, `psutil`, D-Bus de systemd y cursor incremental de journald).
  - Agrupación de árboles de procesos en aplicaciones lógicas mediante `cgroups` (sin inventar identidades).
  - Detección determinista de anomalías y cálculo de señales de riesgo (`RiskEngine`).
  - Coalescencia temporal de eventos (ventana de 3 segundos para evitar ráfagas duplicadas).
  - Puntuación matemática explicable (0 a 100) y control de flujo por *token bucket* (anti-spam con preemption de eventos críticos).
  - Sanitización estricta de privacidad (enmascaramiento de tokens, contraseñas y rutas personales).
  - Persistencia asíncrona de eventos y sesiones en SQLite (modo WAL).
  - Gestión de No Molestar (`DNDManager`) y degradación elegante de fuentes.
  - Orquestación de la cola de audio y despacho a los motores TTS.
- **Responsabilidad de Gemini (La Capa de Explicación Cognitiva):**
  - Recibe **únicamente** un contexto reducido y previamente sanitizado (`GeminiContext`).
  - Traduce los números crudos del evento en una explicación natural, concisa (1 o 2 oraciones) y no técnica en español comprensible para cualquier usuario.
  - **Gemini NO decide qué monitorear, NO ejecuta acciones en el sistema y NO accede a archivos privados.**

### 1.3 Generación y Reproducción de Audio
La narración auditiva sigue una cascada estricta y desacoplada:
1. **Piper TTS (Motor Primordial):** Síntesis neuronal local de alta calidad, ejecutada directamente en la CPU mediante modelos ONNX, sin latencia de red ni consumo de ancho de banda.
2. **`espeak-ng` (Respaldo Local):** Sintetizador por formantes ultra-ligero de respaldo local, garantizando voz incluso si no hay modelos Piper instalados.
3. **Gemini Audio (Último Recurso en la Nube):** Generación remota en la nube a la que solo se recurre si los motores locales fallan.

El reproductor (`SystemAudioPlayer`) utiliza herramientas nativas del sistema (`aplay`, `paplay` o `ffplay`) en un hilo en segundo plano no bloqueante.

### 1.4 Qué información se recopila y cuál se descarta
- **Información recopilada:** Consumo de CPU por proceso y global, memoria RSS, uso de Swap, métricas de presión (`PSI`), estado de batería, unidades de systemd y mensajes de fallo del kernel en journald.
- **Información descartada o enmascarada:** Argumentos sensibles de líneas de comando (`--password`, `--token`, `--api-key`), tokens Bearer, JWTs, claves AWS, credenciales incrustadas en URLs y la ruta del directorio `$HOME` (sustituida por `~`).
- **Privacidad de Sensores:** **NUNCA se graba ni se analiza el contenido del micrófono ni de la cámara.** El detector DND únicamente verifica el estado de descriptores en `/proc/asound` y dispositivos en `/sys/class/video4linux` para saber si otra aplicación los está usando.

### 1.5 Tiempo Real y Limitaciones
El monitor opera bajo el concepto de **tiempo real blando (soft real-time)**:
- El muestreo se produce en ciclos periódicos configurables (por defecto cada 5 s con corriente eléctrica y cada 15 s con batería).
- Existe una ventana de coalescencia de 3 segundos para estabilizar ráfagas antes de puntuar.
- No es un sistema de tiempo real estricto (RTOS) y no debe utilizarse para control de procesos industriales de misión crítica donde se requieran garantías deterministas en microsegundos.

### 1.6 Flujo de Datos del Sistema
```
Linux Kernel (/proc, /sys, psutil, dbus, journald)
   │
   ▼
Collectors Desacoplados (System, Process, Systemd, Journald)
   │
   ▼
Normalización & Agrupación por cgroups (SystemContextBuilder)
   │
   ▼
Detección de Eventos & Señales de Riesgo (RuleBasedDetector & RiskEngine)
   │
   ▼
Coalescencia (EventGrouper) & Puntuación (ScoringEngine)
   │
   ▼
Control de Flujo (PriorityQueue & Token Bucket)
   │
   ├── [Modo DND Activo] ──> Guardado en SQLite (DND/Silenciado)
   │
   ▼ [Permitido]
Sanitización de Privacidad (PrivacySanitizer)
   │
   ▼
Análisis Cognitivo con IA (GeminiClient / AnalysisAgent)
   │
   ▼
Cola de Audio Asíncrona (AudioQueueManager: Piper -> espeak -> Gemini)
   │
   ▼
Reproducción Física (SystemAudioPlayer -> Parlantes)
```

> [!IMPORTANT]
> **Sin Interacción Conversacional:** El agente **NO escucha por el micrófono**, **NO realiza reconocimiento de voz** ni recibe órdenes habladas. Es un sistema exclusivamente de salida informativa (unidireccional).

---

## 2. Estado Actual y Roadmap

El desarrollo se ha completado al 100% hasta el **MR 18: CI & Production Hardening**. La siguiente tabla refleja el estado verificado contra el código fuente, los tests y el empaquetado:

| MR | Nombre | Estado | Descripción Verificada |
|:---|:---|:---:|:---|
| **MR 01** | Estructura y Herramientas | **COMPLETADO** | Configuración base del repositorio con `pytest`, `flake8`, `mypy`, `pylint`. |
| **MR 02** | Configuración y Dominio | **COMPLETADO** | Configuración centralizada inmutable con `Pydantic Settings` y modelos base. |
| **MR 03** | Process Collector | **COMPLETADO** | Recolección de procesos con `psutil` y sanitización de comandos. |
| **MR 04** | System Metrics Collectors | **COMPLETADO** | Métricas de CPU, Memoria (`MemAvailable`), Swap, PSI y batería. |
| **MR 05** | Application Grouping | **COMPLETADO** | Agrupación de subprocesos por aplicación lógica y `cgroups`. |
| **MR 06** | Context Enrichment | **COMPLETADO** | Enriquecimiento con promedios de carga y detección de anomalías locales. |
| **MR 07** | Prioritization & Flow | **COMPLETADO** | Scoring explicable (0-100), coalescencia de 3s y token bucket anti-spam. |
| **MR 08** | Persistencia & Knowledge Base | **COMPLETADO** | SQLite asíncrono (WAL) y catálogo curado de 250 procesos conocidos. |
| **MR 09** | Gemini Foundation | **COMPLETADO** | `PrivacySanitizer`, `GeminiContextBuilder` y `CircuitBreaker`. |
| **MR 10** | Gemini Analysis Agent | **COMPLETADO** | Respuestas estructuradas en español y modo de prueba offline. |
| **MR 11** | Audio Output Architecture | **COMPLETADO** | Cascada: **1º Piper TTS (Primordial)** $\to$ **2º espeak-ng** $\to$ **3º Gemini Audio**. |
| **MR 12** | Narration Pipeline | **COMPLETADO** | Pipeline end-to-end integrado conectando recolección, IA y audio. |
| **MR 13** | DND & Degradation | **COMPLETADO** | DND pasivo (mic/cámara/juegos) y degradación independiente por fuente. |
| **MR 14** | Performance & Replay | **COMPLETADO** | Consumo medido (<2% CPU, <100 MB RAM), `ReplayEngine` y benchmark CLI. |
| **MR 15** | CLI y Reportes de Sesión | **COMPLETADO** | Comando unificado `narrator` y generación de informes en HTML y PDF. |
| **MR 16** | Linux Integrations | **COMPLETADO** | `systemd` D-Bus con caché TTL, `journald` incremental y `RiskEngine`. |
| **MR 17** | Packaging & Service | **COMPLETADO** | Empaquetado `pipx`/`venv`, servicio systemd de usuario con sandboxing sin root. |
| **MR 18** | CI & Production Hardening | **COMPLETADO** | Matriz de CI en GitHub Actions, 247 tests pasando, >84% cobertura y linters limpios. |

*Para más detalles sobre el historial de entregas y el roadmap futuro, consulta [`docs/ROADMAP.md`](file:///c:/Users/USUARIO/Desktop/Projects/voicemonitor/voice-monitor/docs/ROADMAP.md).*

---

## 3. Requisitos Previos

### 3.1 Requisitos del Sistema
- **Python:** Versión **3.10 o superior** (probado en 3.10, 3.11 y 3.12).
- **Sistemas Operativos Soportados:**
  - Ubuntu 22.04 LTS (Jammy Jellyfish).
  - Ubuntu 24.04 LTS (Noble Numbat).
  - Debian 12 (Bookworm).
  - WSL2 sobre Windows 10/11.
- **Librerías del Sistema requeridas para compilación y D-Bus:**
  - `gcc`, `pkg-config`, `libsystemd-dev`, `libdbus-1-dev`.
- **Servidor y utilidades de Audio:**
  - `alsa-utils` (provee `aplay`), `espeak-ng` (provee síntesis de respaldo).
  - Piper TTS (opcional para voz neuronal de alta calidad).
- **Recursos de Hardware Medidos:**
  - **RAM:** Inferior a 100 MB (consumo nominal medido: 45 MB a 65 MB sin voz en reproducción).
  - **CPU:** Menor al 2% de un núcleo en estado estable (medido: 0.4% a 1.2% por tick).

### 3.2 Matriz de Compatibilidad de Plataforma

| Capacidad | Ubuntu Nativo (22.04 / 24.04) | Debian 12 Nativo | WSL2 (Windows 11) | Contenedor Docker Estándar |
|:---|:---:|:---:|:---:|:---:|
| **systemd (PID 1)** | Sí | Sí | Requiere `/etc/wsl.conf` | Rara vez (requiere init especial) |
| **Servicio de Usuario (`systemctl --user`)** | Sí | Sí | Con systemd activo | No |
| **D-Bus del Sistema** | Sí | Sí | Con systemd activo | Solo con socket compartido |
| **journald Incremental** | Sí | Sí | Con systemd activo | No |
| **Presión PSI (`/proc/pressure`)** | Sí | Sí | Según kernel WSL | Solo si el host lo expone |
| **Batería (`/sys/class/power_supply`)** | Sí (Laptops) | Sí (Laptops) | No (Virtualizado) | No |
| **Audio por Parlantes** | Sí (PipeWire / Pulse) | Sí (Pulse / ALSA) | Requiere WSLg (`pulse`) | Requiere reenviar socket de audio |

---

## 4. Instalación Paso a Paso

### 4.1 Instalación con `pipx` (Recomendada para usuarios de Ubuntu 24.04 y Debian 12)
En distribuciones modernas con PEP 668, `pipx` permite instalar la aplicación de forma aislada sin ensuciar los paquetes del sistema:

```bash
# 1. Instalar librerías del sistema y pipx
sudo apt update && sudo apt install -y \
    git python3 python3-pip python3-venv gcc pkg-config \
    libsystemd-dev libdbus-1-dev alsa-utils espeak-ng pipx
pipx ensurepath

# 2. Clonar el repositorio
git clone https://github.com/usuario/ubuntu-voice-monitor.git
cd ubuntu-voice-monitor

# 3. Instalar con dependencias de reportes
pipx install ".[reports]"

# 4. Validar la instalación
narrator --help
narrator status
```

### 4.2 Instalación en Entorno Virtual `venv` (Para desarrollo)
```bash
# 1. Clonar el repositorio
git clone https://github.com/usuario/ubuntu-voice-monitor.git
cd ubuntu-voice-monitor

# 2. Crear y activar el entorno virtual
python3 -m venv .venv
source .venv/bin/activate

# 3. Actualizar pip e instalar dependencias del proyecto, desarrollo y reportes
pip install --upgrade pip
pip install -e ".[dev,reports]"

# 4. Comprobar instalación
narrator status
```

### 4.3 Configuración del archivo de entorno
```bash
cp .env.example .env
```
Edita `.env` para añadir tu `GEMINI_API_KEY` (si deseas análisis con IA) o la ruta de tu modelo Piper.

*Para instrucciones detalladas sobre WSL2 y resolución de problemas de dependencias, consulta [`docs/INSTALLATION.md`](file:///c:/Users/USUARIO/Desktop/Projects/voicemonitor/voice-monitor/docs/INSTALLATION.md).*

---

## 5. Configuración y Variables de Entorno

### 5.1 Tabla Resumen de Variables

| Variable | Descripción | Obligatoria | Valor por Defecto |
|:---|:---|:---:|:---|
| `APP_ENV` | Entorno de ejecución (`development`, `test`, `production`). | No | `development` |
| `LOG_LEVEL` | Nivel de registro (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). | No | `INFO` |
| `COLLECTOR_INTERVAL_S` | Segundos entre lecturas conectado a corriente. | No | `5.0` |
| `COLLECTOR_BATTERY_INTERVAL_S`| Segundos entre lecturas operando con batería ($\ge$ `interval_s`). | No | `15.0` |
| `COLLECTOR_ADAPTIVE` | Adapta la frecuencia de sondeo a la actividad del sistema. | No | `true` |
| `NARRATION_VERBOSITY` | Nivel de detalle de las narraciones (`minimal`, `normal`, `verbose`). | No | `normal` |
| `NARRATION_MIN_GAP_S` | Segundos mínimos de silencio entre narraciones consecutivas. | No | `10.0` |
| `NARRATION_MAX_BURST` | Máximo de narraciones seguidas antes de enfriamiento (token bucket). | No | `3` |
| `NARRATION_EVENT_TTL_S` | Tiempo de vida de un evento en cola antes de expirar. | No | `60.0` |
| `NARRATION_PIPER_MODEL_PATH` | Ruta absoluta al archivo `.onnx` de voz de Piper TTS. | No | `None` |
| `GEMINI_ENABLED` | Habilita el análisis inteligente con Google Gemini. | No | `false` |
| `GEMINI_MODEL` | Nombre del modelo de Gemini a consultar. | No | `gemini-2.5-flash` |
| `GEMINI_API_KEY` | Clave secreta de Google AI Studio. | **Sí** (si `GEMINI_ENABLED=true`) | `None` |
| `STORAGE_DB_PATH` | Ruta del archivo de base de datos SQLite local. | No | `~/.local/share/ubuntu-voice-monitor/events.db` |
| `PRIVACY_REDACT_HOME` | Sustituye `/home/<usuario>` por `~` en rutas. | No | `true` |
| `DND_ENABLED` | Activa el modo No Molestar manualmente desde configuración. | No | `false` |

### 5.2 Precedencia de Configuración
La configuración se resuelve en el siguiente orden de prioridad:
1. **Argumentos de línea de comandos** (`--no-audio`, `--debug`, `--verbosity`, etc.).
2. **Variables de entorno del sistema** exportadas en el shell (`export GEMINI_ENABLED=true`).
3. **Archivo de variables** (`.env` local o ruta dada por `--config`).
4. **Valores por defecto del código** definidos en `app.core.config.Settings`.

*Para el manual exhaustivo de configuración, consulta [`docs/CONFIGURATION.md`](file:///c:/Users/USUARIO/Desktop/Projects/voicemonitor/voice-monitor/docs/CONFIGURATION.md).*

---

## 6. Cómo Ejecutar el Proyecto

### 6.1 El Comando Principal: `narrator`

El ejecutable `narrator` (instalado en `$PATH` o en el entorno virtual) es la interfaz central de control:

```bash
# 1. Consultar el estado y diagnóstico completo de todos los subsistemas:
narrator status

# 2. Iniciar el monitor en primer plano (ideal para desarrollo y visualización de logs):
narrator start -f

# 3. Iniciar el monitor en segundo plano (modo daemon con archivo PID):
narrator start

# 4. Iniciar en modo silencioso (sin sonido por altavoces, solo eventos y logs):
narrator --no-audio start -f

# 5. Iniciar con depuración detallada:
narrator --debug start -f

# 6. Pausar manualmente las narraciones (Modo No Molestar sin perder eventos):
narrator pause --reason "Reunión de trabajo"

# 7. Reanudar las narraciones de audio:
narrator resume

# 8. Consultar la sesión actual y estadísticas de eventos:
narrator session

# 9. Generar un informe completo de la sesión en HTML o PDF:
narrator report --format html
narrator report --format pdf -o reporte.pdf

# 10. Detener el monitor en segundo plano:
narrator stop
```

### 6.2 Ejemplo Ilustrativo de Salida de `narrator status`

```text
============================================================
          ESTADO DE UBUNTU VOICE MONITOR          
============================================================
Estado General:     RUNNING (PID: 28410)
Sesión Activa:      session_20261013_230000
Eventos en sesión:  14
------------------------------------------------------------
[0] PLATAFORMA Y SUBSISTEMAS:
  - Distribución:    Ubuntu 24.04 LTS
  - Entorno WSL:     No (Linux nativo)
  - systemd:         OK (PID 1 activo)
  - systemd Usuario: OK (Socket disponible)
  - D-Bus:           OK (Conectado a org.freedesktop.systemd1)
  - journald:        OK (Cursor incremental activo)
  - Audio Backend:   PIPEWIRE (Servidor detectado)
  - Presión PSI:     OK (cpu, memory, io)
  - Batería Física:  OK (Cargando, 88%)
------------------------------------------------------------
[1] RECOLECTORES (COLLECTORS):
  - System         : OK
  - Processes      : OK
  - Psi            : OK
  - Battery        : OK
  - Systemd        : OK
  - Journald       : OK
------------------------------------------------------------
[2] INTELIGENCIA ARTIFICIAL (GEMINI):
  - Habilitado:      True
  - Modelo:          gemini-2.5-flash
  - Circuit Breaker: CLOSED (Saludable)
------------------------------------------------------------
[3] SALIDA DE AUDIO:
  - Modo:            ACTIVO (Voz)
  - Motor Primordial:Piper TTS (es_ES-davefx-medium)
  - Motor Respaldo:  espeak-ng (es-la)
------------------------------------------------------------
[4] MODO NO MOLESTAR (DND):
  - Estado DND:      INACTIVO
  - Micrófono ocupado: False
  - Cámara ocupada:    False
============================================================
```

### 6.3 Demostración Local Inmediata (Sin requerir API Keys ni configuración)
Para comprobar el funcionamiento del pipeline completo en tu propia máquina en 5 segundos:
```bash
# Demo en modo texto/silencioso con respuestas de IA simuladas:
python scripts/demo_pipeline.py --no-audio --test-gemini --iterations 5

# Demo con salida física de voz por parlantes (si tienes audio activo):
python scripts/demo_pipeline.py --test-gemini
```

---

## 7. Configuración y Funcionamiento de Gemini

### 7.1 Integración y SDK
- **SDK Oficial:** Utiliza la librería `google-generativeai` configurada de forma aislada en `GeminiClient` (`app.core.gemini`).
- **Modelo Predeterminado:** `gemini-2.5-flash`.
- **Estructura de Datos Enviada:** Únicamente se envía un objeto `GeminiContext` que contiene el resumen seguro del evento (`SafeEventSummary`: nombre de aplicación sanitizado, tipo de evento, severidad, puntaje y duración) y las métricas globales del sistema (promedio de carga y % de memoria).
- **Respuesta Estructurada:** El modelo genera respuestas orientadas a personas mediante esquemas estructurados de análisis (`AnalysisResult`) que priorizan la claridad y la brevedad.

### 7.2 Resiliencia y Manejo de Errores
- **Circuit Breaker:** Si se producen 2 fallos consecutivos de red o API, el circuito conmuta a `OPEN` suspendiendo las llamadas a la nube durante un periodo de enfriamiento (30 segundos), evitando saturar el sistema o agotar cuotas.
- **Backoff Exponencial:** Ante códigos de error 429 (`ResourceExhausted` por límites de tasa), el cliente reintenta con backoff exponencial suave ($2^\text{intento}$ segundos).
- **Degradación Elegante:** Si Gemini no responde, la red cae o la API key es inválida, el monitor **no se detiene**: recurre de inmediato al resumen sintético del detector local y lo narra sin interrupciones.

---

## 8. Subsistema de Audio y Motores de Voz

El subsistema de audio está diseñado para garantizar que **el agente nunca bloquee el ciclo de monitoreo**:

1. **Prioridad 1 — Piper TTS (Motor Primordial):** Sintetizador neuronal de voz rápido y de alta fidelidad que se ejecuta 100% offline. Requiere configurar `NARRATION_PIPER_MODEL_PATH`.
2. **Prioridad 2 — `espeak-ng` (Respaldo Local):** Sintetizador liviano disponible de forma estándar en Ubuntu mediante `sudo apt install espeak-ng`. Actúa como fallback si Piper no está disponible o falla.
3. **Prioridad 3 — Gemini Audio (Último Recurso):** Generación remota en la nube a la que solo se recurre si los motores locales no están operativos.
4. **Caché SHA-256:** Las frases idénticas sintetizadas se guardan en caché temporal en disco, evitando volver a invocar el motor de voz ante eventos recurrentes.
5. **Preemption:** Si el reproductor está emitiendo un mensaje ordinario y ocurre un evento `CRITICAL` (ej. Kernel OOM o fallo crítico), la cola cancela de inmediato la reproducción actual y reproduce la alerta crítica.

---

## 9. Arquitectura y Estructura del Código

El proyecto sigue una arquitectura orientada a dominio, desacoplada y estrictamente de solo lectura:

```
app/
├── collectors/      # Observación del kernel, procfs, sysfs, psutil, systemd y journald
├── core/            # Pipeline, scoring, agrupador, token bucket, DND, Gemini y audio
├── domain/          # Modelos inmutables Pydantic (Event, Context, Snapshots, Risk)
└── storage/         # Base de datos SQLite (WAL) y catálogo de 250 procesos conocidos
```

*Para el diagrama técnico detallado y las descripciones por módulo, consulta [`docs/ARCHITECTURE.md`](file:///c:/Users/USUARIO/Desktop/Projects/voicemonitor/voice-monitor/docs/ARCHITECTURE.md).*

---

## 10. Base de Datos y Almacenamiento

### 10.1 Esquema y Motor SQLite
- **Ubicación:** `~/.local/share/ubuntu-voice-monitor/events.db` (creada automáticamente con permisos `0700`).
- **Modo WAL (Write-Ahead Logging):** Permite lecturas concurrentes sin bloquear la cola de escritura.
- **Escritura Asíncrona:** La clase `BackgroundDatabase` despacha las inserciones a través de una cola en memoria procesada por un hilo dedicado en segundo plano, protegiendo al pipeline de latencias de disco.
- **Tablas:**
  - `sessions`: Registro de cada arranque, parada, duración y métricas acumuladas.
  - `events`: Historial de eventos detectados, puntajes, decisiones (`SPOKEN`, `DND`, `THRESHOLD_OMITTED`) y resúmenes.
  - `source_health`: Historial de transiciones de estado de los recolectores (`OK`, `DEGRADED`, `DISABLED`).
  - `process_knowledge`: Catálogo curado de 250 firmas de procesos precargadas en la primera ejecución (`INSERT OR IGNORE`).

---

## 11. Logs y Solución de Problemas

### 11.1 Registro y Depuración
Por defecto, los logs se emiten en consola con formato estandarizado y nivel `INFO`. Para activar el registro detallado:
```bash
narrator --debug start -f
```

### 11.2 Tabla Rápida de Solución de Problemas

| Problema | Causa Probable | Solución |
|:---|:---|:---|
| **No se escucha voz** | Servidor de audio no detectado, o DND activo. | Probar sonido con `aplay /usr/share/sounds/alsa/Front_Center.wav`. Si DND está activo, reanudar con `narrator resume`. En WSL sin WSLg, usar `--no-audio`. |
| **Error de API Key de Gemini** | `GEMINI_ENABLED=true` sin clave en `.env`. | Añadir clave válida en `.env` o desactivar con `GEMINI_ENABLED=false`. |
| **`systemd no disponible`** | Ejecución en contenedor Docker o WSL antiguo. | En WSL2, agregar `systemd=true` en `/etc/wsl.conf` y reiniciar con `wsl --shutdown`. |
| **Fuente `psi` degradada** | El kernel no soporta `/proc/pressure`. | Normal en kernels legacy o WSL1; el agente continúa operando sin PSI. |

*Para la guía completa de diagnóstico de audio, permisos y SQLite, consulta [`docs/TROUBLESHOOTING.md`](file:///c:/Users/USUARIO/Desktop/Projects/voicemonitor/voice-monitor/docs/TROUBLESHOOTING.md).*

---

## 12. Tests y Calidad

La suite de pruebas automatizadas está diseñada para garantizar calidad y robustez sin requerir acceso a Internet ni hardware de sonido:

```bash
# 1. Ejecutar toda la suite de pruebas (247 tests):
pytest

# 2. Ejecutar con análisis de cobertura de código (>84%):
pytest --cov=app --cov-report=term-missing

# 3. Ejecutar una prueba individual específica:
pytest tests/collectors/test_process_collector.py -k "test_plain_cmdline"

# 4. Verificación estricta de estilo (longitud <= 90 caracteres):
flake8 app tests scripts packaging

# 5. Verificación de tipos estricta con Mypy:
mypy app

# 6. Verificación de errores críticos con Pylint:
pylint app --errors-only

# 7. Ejecutar benchmark de rendimiento:
python scripts/benchmark.py --scenario all --ticks 20
```

---

## 13. Seguridad y Privacidad

- **Principio de Solo Lectura:** El agente únicamente inspecciona descriptores y bitácoras del kernel. **Nunca mata, modifica, frena ni reinicia procesos del usuario o del sistema.**
- **Sin Privilegios de Root:** El agente se ejecuta exclusivamente como usuario no privilegiado. No requiere `sudo`, `pkexec` ni helpers con `setuid`.
- **Privacidad Auditiva:** Los secretos de consola nunca se leen en voz alta ni se pasan a los motores de audio.
- **Aislamiento en la Nube:** Únicamente se transmiten a Gemini resúmenes de eventos previamente anonimizados. Si el usuario no desea interactuar con la nube, basta con mantener `GEMINI_ENABLED=false`.

---

## 14. Servicio systemd de Usuario

El monitor incluye una unidad de servicio systemd de usuario con sandboxing estricto:

```bash
# 1. Instalar y habilitar el servicio de usuario:
narrator service install
# O habilitar e iniciar directamente con systemctl:
systemctl --user enable --now voice-monitor.service

# 2. Consultar el estado del servicio:
narrator service status
# O directamente con systemctl:
systemctl --user status voice-monitor.service

# 3. Seguir los logs en tiempo real mediante journalctl:
journalctl --user -u voice-monitor.service -f

# 4. Detener o reiniciar el servicio:
systemctl --user stop voice-monitor.service
systemctl --user restart voice-monitor.service

# 5. Desinstalar el servicio:
narrator service uninstall
```

**Medidas de Seguridad de la Unidad:**
- `ProtectSystem=strict`: Monta `/usr`, `/boot` y `/etc` en modo solo lectura.
- `ProtectHome=read-only`: Protege el directorio de usuario excepto las rutas explícitas de configuración y base de datos (`~/.local/share/ubuntu-voice-monitor`).
- `NoNewPrivileges=yes`: Impide elevar privilegios mediante binarios setuid.
- `CapabilityBoundingSet=`: Elimina todas las capacidades administrativas de Linux.

---

## 15. Actualización, Desinstalación y Mantenimiento

### Actualización
```bash
# Si se instaló con pipx:
pipx upgrade ubuntu-voice-monitor

# Si se instaló en entorno virtual venv:
git pull
pip install --upgrade pip
pip install -e ".[dev,reports]"
```

### Respaldo de Historial
Para conservar el historial de eventos y sesiones registradas, realiza una copia del directorio:
```bash
cp -r ~/.local/share/ubuntu-voice-monitor ~/backup-voice-monitor-$(date +%F)
```

### Desinstalación Limpia
```bash
# 1. Desinstalar el servicio systemd:
narrator service uninstall

# 2. Desinstalar el paquete de Python:
pipx uninstall ubuntu-voice-monitor

# 3. (Opcional) Eliminar base de datos local:
rm -rf ~/.local/share/ubuntu-voice-monitor ~/.config/ubuntu-voice-monitor
```

---

## 16. Información para Desarrolladores

Para contribuir al proyecto:
- **Estilo:** Sigue PEP 8 con líneas $\le 90$ caracteres.
- **Tipado:** Tipado estricto verificado con `mypy app`.
- **Extensión:** Consulta [`docs/DEVELOPMENT.md`](file:///c:/Users/USUARIO/Desktop/Projects/voicemonitor/voice-monitor/docs/DEVELOPMENT.md) para aprender a:
  - Añadir nuevos recolectores de métricas.
  - Registrar nuevos tipos de eventos y reglas.
  - Incorporar entradas al catálogo curado de 250 procesos en [`knowledge_data.json`](file:///c:/Users/USUARIO/Desktop/Projects/voicemonitor/voice-monitor/app/storage/knowledge_data.json).
  - Integrar nuevos adaptadores de síntesis de voz.

---

## 17. Documentación Complementaria

Para profundizar en áreas específicas del proyecto, consulta la documentación modular en el directorio [`docs/`](file:///c:/Users/USUARIO/Desktop/Projects/voicemonitor/voice-monitor/docs/):

- 📜 [**`docs/ROADMAP.md`**](file:///c:/Users/USUARIO/Desktop/Projects/voicemonitor/voice-monitor/docs/ROADMAP.md): Tabla de estado de todos los MRs, dependencias y próximos pasos.
- 🚀 [**`docs/INSTALLATION.md`**](file:///c:/Users/USUARIO/Desktop/Projects/voicemonitor/voice-monitor/docs/INSTALLATION.md): Guía de instalación paso a paso en Ubuntu Nativo, Debian 12 y WSL2.
- ⚙️ [**`docs/CONFIGURATION.md`**](file:///c:/Users/USUARIO/Desktop/Projects/voicemonitor/voice-monitor/docs/CONFIGURATION.md): Referencia exhaustiva de variables de entorno y precedencia.
- 🏗️ [**`docs/ARCHITECTURE.md`**](file:///c:/Users/USUARIO/Desktop/Projects/voicemonitor/voice-monitor/docs/ARCHITECTURE.md): Diagramas de flujo, diseño de componentes y arquitectura interna.
- 🔍 [**`docs/TROUBLESHOOTING.md`**](file:///c:/Users/USUARIO/Desktop/Projects/voicemonitor/voice-monitor/docs/TROUBLESHOOTING.md): Diagnóstico de problemas de audio, permisos, WSL y SQLite.
- 💻 [**`docs/DEVELOPMENT.md`**](file:///c:/Users/USUARIO/Desktop/Projects/voicemonitor/voice-monitor/docs/DEVELOPMENT.md): Guía de contribución, estándares de código y adición de módulos.
