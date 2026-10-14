# Estado Actual y Roadmap de Ubuntu Voice Monitor

Este documento detalla el estado real del desarrollo del **Ubuntu Voice Monitor** (Narrador Linux), cubriendo los Merge Requests (MRs) completados, las capacidades verificadas en código y las funcionalidades planificadas para versiones futuras.

---

## 1. Tabla de Estado de Merge Requests (MR 01 – MR 18)

| MR | Nombre | Estado | Descripción Verificada |
|:---|:---|:---:|:---|
| **MR 01** | Estructura y Herramientas | **COMPLETADO** | Configuración base del repositorio con `pytest`, `flake8`, `mypy`, `pylint` y `pyproject.toml`. |
| **MR 02** | Configuración y Dominio | **COMPLETADO** | Configuración centralizada inmutable con `Pydantic Settings`, soporte de archivos `.env`, y modelos base de dominio (`DomainModel`, enums de severidad y tipos de evento). |
| **MR 03** | Process Collector | **COMPLETADO** | Recolección no invasiva de procesos mediante `psutil` (PID, CPU%, memoria RSS, estado, usuario) y sanitización de argumentos en línea de comandos. |
| **MR 04** | System Metrics Collectors | **COMPLETADO** | Métricas del sistema: CPU global, memoria disponible (`MemAvailable`), Swap, métricas de presión del kernel (`PSI` en `/proc/pressure/`) y estado de batería (`/sys/class/power_supply/`). |
| **MR 05** | Application Grouping | **COMPLETADO** | Agrupación de árboles de subprocesos en entidades de aplicación lógicas utilizando `cgroups` (systemd scopes/slices) y jerarquía de procesos sin inventar identidades. |
| **MR 06** | Context Enrichment & History | **COMPLETADO** | Integración del contexto del sistema (`SystemContext`) con historial de métricas, ventanas de promedio de carga y detección de anomalías locales. |
| **MR 07** | Event Prioritization & Flow | **COMPLETADO** | Motor de puntuación explicable (`ScoringEngine`), coalescencia temporal de 3 segundos (`EventGrouper`), cola con TTL de 30 s (`PriorityQueue`) y control de saturación por token bucket (`FlowController`). |
| **MR 08** | Persistencia y Knowledge Base | **COMPLETADO** | Base de datos SQLite en modo WAL con cola asíncrona no bloqueante (`BackgroundDatabase`), repositorios de eventos y catálogo curado de 250 procesos conocidos con fallback a `UNKNOWN`. |
| **MR 09** | Gemini Integration Foundation | **COMPLETADO** | Sanitizador de privacidad (`PrivacySanitizer`), constructor de contexto seguro (`GeminiContextBuilder`) y cliente con circuit breaker y backoff exponencial (`GeminiClient`). |
| **MR 10** | Gemini Analysis Agent | **COMPLETADO** | Agente de análisis de contexto (`AnalysisAgent`) con respuestas estructuradas en español, prompts versionados y soporte para modo de prueba sin consumo de red. |
| **MR 11** | Audio Output Architecture | **COMPLETADO** | Cola de audio asíncrona (`AudioQueueManager`) con caché SHA-256 de audios sintetizados y cascada desacoplada: **1º Piper TTS (Primordial)** → **2º espeak-ng (Local)** → **3º Gemini Audio (Nube/Último recurso)**. |
| **MR 12** | End-to-End Narration Pipeline | **COMPLETADO** | Ensamblado del pipeline completo (`NarrationPipeline`) que conecta recolección, detección, puntuación, análisis con IA y narración por audio. |
| **MR 13** | DND & Graceful Degradation | **COMPLETADO** | Gestor de No Molestar (`DNDManager`) con detección pasiva de actividad (micrófono, cámara, modo juego, inhibición de escritorio) y degradación independiente por fuente en `SourceHealthManager`. |
| **MR 14** | Performance & Replay Testing | **COMPLETADO** | Motor de reproducción histórica (`ReplayEngine`), fixtures sintéticos (`idle`, `cpu_spike`, `docker`, `electron_saturation`), métricas de consumo (CPU < 2.0%, RAM < 100 MB) y benchmark reproducible (`scripts/benchmark.py`). |
| **MR 15** | CLI y Reportes de Sesión | **COMPLETADO** | Comando unificado `narrator` (`start`, `stop`, `status`, `pause`, `resume`, `session`, `report`, `service`) y generación de informes de sesión en HTML y PDF (`ReportService`). |
| **MR 16** | Advanced Linux Integrations | **COMPLETADO** | Módulos desacoplados para `systemd` (D-Bus con caché TTL), `journald` (cursor incremental para OOM y fallos) y motor de señales de riesgo comprobadas (`RiskEngine`). |
| **MR 17** | Linux Service & Packaging | **COMPLETADO** | Empaquetado estandarizado para Ubuntu 22.04/24.04 y Debian 12 (`pipx`/`venv`), servicio systemd de usuario con sandboxing estricto de mínimos privilegios sin root (`packaging/systemd/voice-monitor.service`). |
| **MR 18** | CI & Production Hardening | **COMPLETADO** | Matriz de CI en GitHub Actions (Ubuntu 22.04 LTS / Python 3.10, Ubuntu 24.04 LTS / Python 3.12, Debian 12 / Python 3.11), 247 pruebas pasando, >84% cobertura, 0 errores en linters y base de conocimiento con 250 procesos. |

---

## 2. Estado Actual de la Implementación

### Funcionalidades Completadas y Verificadas (100% Funcionales)
- **Recolección Integral del SO:** Procesos (`psutil`), CPU/Memoria/Swap (`procfs`), Presión (`PSI`), Batería (`sysfs`), Unidades de systemd (D-Bus) y Bitácoras de fallos/OOM (`journald`).
- **Sanitización de Privacidad:** Enmascaramiento de tokens, credenciales en URL, claves Bearer/JWT/AWS y sustitución del directorio `$HOME` antes de construir el contexto de Gemini.
- **Detección y Puntuación Determinista:** Detección basada en reglas y anomalías, puntuación explicable (0 a 100), ordenamiento por prioridad y supresión de spam mediante token bucket.
- **Análisis con IA (Gemini):** Cliente aislado con `CircuitBreaker` (conmutación automática a `OPEN` tras 2 fallos consecutivos y recuperación por timeout), prompts estructurados y modo de simulación offline (`--test-gemini`).
- **Salida de Audio en Cascada:**
  1. **Piper TTS:** Voz neuronal offline, primordial, de baja latencia y sin consumo de red.
  2. **espeak-ng:** Respaldo local ultra-ligero para entornos sin modelos neuronales.
  3. **Gemini Audio:** Síntesis remota en la nube utilizada estrictamente como último recurso.
- **Modo No Molestar (DND):** Pausa manual global, detección pasiva de uso de micrófono/cámara sin capturar flujos, detección de reproductores multimedia e inhibidores de escritorio. Los eventos silenciados se persisten con decisión `DND` sin perderse.
- **Persistencia en SQLite:** Base de datos en modo WAL con cola de escritura en hilo secundario para eventos, sesiones, salud de fuentes y catálogo de 250 procesos.
- **Línea de Comandos (`narrator`):** Inicio en primer/segundo plano, detención, diagnóstico detallado de estado (`narrator status`), gestión de DND (`pause`/`resume`), consulta de sesiones y exportación de informes en HTML/PDF.
- **Servicio systemd de Usuario:** Unidad en espacio de usuario (`voice-monitor.service`) con aislamiento estricto de sistema de archivos (`ProtectSystem=strict`, `ProtectHome=read-only`) y sin privilegios de root.

### Funcionalidades Parciales o Dependientes del Entorno
- **Aceleración de Audio en WSL2:** Requiere WSLg (disponible en Windows 11 o Windows 10 con compilaciones recientes). Si WSLg no está disponible, el monitor conmuta a modo silencioso (`--no-audio`) manteniendo intacta la recolección, el análisis y la persistencia.
- **Métricas de Batería en Máquinas Virtuales:** En entornos virtualizados (WSL, VMs, contenedores Docker), `/sys/class/power_supply` no expone baterías físicas; el sistema degrada la fuente a `DEGRADED` de manera transparente.
- **Soporte de systemd en WSL:** Versiones de WSL sin `systemd=true` en `/etc/wsl.conf` no arrancan `systemd` como PID 1, lo que inhabilita el colector de systemd y el servicio de usuario.

---

## 3. Roadmap Futuro (Post MR 18)

Las siguientes funcionalidades no forman parte del núcleo inicial del monitor y se encuentran planificadas para versiones posteriores:

1. **Descargador Automatizado de Voces Piper (`narrator voices download`):**
   - Asistente interactivo en consola para descargar e instalar modelos `.onnx` en español (ej. `es_ES-davefx-medium`, `es_ES-enrique-medium`) directamente al directorio `~/.local/share/piper/`.
2. **Notificaciones Visuales de Escritorio (libnotify / D-Bus):**
   - Emisión simultánea de notificaciones en el área de notificaciones de GNOME/KDE cuando un evento crítico sea detectado o durante el modo silencioso (`--no-audio`).
3. **Panel de Monitoreo Web Local (UI de Observabilidad):**
   - Interfaz web ligera embebida opcional (FastAPI/HTMX) para visualizar métricas en tiempo real, gráficos de uso y registro histórico de eventos narrados.
4. **Soporte Multilingüe en Prompts y Voces:**
   - Incorporación de perfiles en inglés (`en_US`) y portugués (`pt_BR`) para las narraciones generadas por Gemini y los adaptadores de TTS.
5. **Empaquetado Nativo en Formato Debian (`.deb`):**
   - Generación de paquetes `.deb` para distribución mediante repositorios APT corporativos o PPA de Launchpad.
