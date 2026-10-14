# Guía de Diagnóstico y Solución de Problemas (Troubleshooting)

Esta guía recopila los problemas frecuentes, causas probables, métodos de diagnóstico y soluciones para **Ubuntu Voice Monitor** (`narrator`).

---

## 1. Comprobación Inicial de Estado y Diagnóstico

Ante cualquier comportamiento anómalo, ejecuta el diagnóstico integrado del CLI:
```bash
narrator status
```
Este comando funciona incluso si la base de datos está vacía, Gemini está desconectado o el audio no está disponible. Imprime el estado de cada subsistema y advertencias específicas del entorno.

Para obtener el registro detallado con trazas de pila completas:
```bash
narrator --debug status
```

---

## 2. Tabla de Problemas Frecuentes y Soluciones

| Problema | Causa Posible | Cómo Comprobarlo | Solución |
|:---|:---|:---|:---|
| **No se escucha voz por los altavoces** | Modo DND activo, falta de servidor de audio, o backend no detectado. | Ejecutar `narrator status`. Revisar si DND está activo o si `Audio Backend` indica `NONE`. Probar sonido con `aplay /usr/share/sounds/alsa/Front_Center.wav`. | 1. Si DND está activo, reanudar con `narrator resume`.<br>2. En WSL, verificar si WSLg está activo o ejecutar con `--no-audio`.<br>3. Instalar reproductor: `sudo apt install alsa-utils espeak-ng`. |
| **Error `GEMINI_API_KEY es obligatoria si GEMINI_ENABLED=true`** | Se habilitó Gemini en `.env` pero no se definió una clave válida. | Inspeccionar el archivo `.env` o la variable de entorno: `echo $GEMINI_API_KEY`. | Definir una clave válida obtenida en [Google AI Studio](https://aistudio.google.com/apikey) o desactivar la IA asignando `GEMINI_ENABLED=false`. |
| **Error 429 / `ResourceExhausted` en Gemini** | Se alcanzó el límite de tasa de la API de Google AI Studio. | Revisar logs con `--debug`. El cliente informará `Gemini Rate Limit Excedido`. | El `CircuitBreaker` interno maneja esto con backoff exponencial. Si persiste, el monitor continúa operando con los resúmenes sintéticos locales sin detenerse. |
| **Advertencia `systemd no está activo como PID 1`** | Ejecución dentro de un contenedor Docker estándar o WSL2 con systemd deshabilitado. | Ejecutar `ps -p 1 -o comm=`. Si devuelve `init` o `bash`, systemd no es PID 1. | En WSL2, agregar `[boot]\nsystemd=true` en `/etc/wsl.conf` y reiniciar con `wsl --shutdown`. En Docker, usar `--no-audio` y considerar que `SystemdCollector` permanecerá en `DISABLED`. |
| **Fuente `psi` en estado `DEGRADED`** | El kernel no tiene compilado soporte de PSI o no monta `/proc/pressure`. | Comprobar si existe la ruta: `ls -la /proc/pressure/cpu`. | En kernels antiguos o WSL1 no existe PSI. El monitor degrada elegantemente la métrica de presión y utiliza el uso de CPU/RAM convencional. |
| **Fuente `battery` en estado `DEGRADED`** | Máquina de escritorio, WSL o máquina virtual sin batería física. | Verificar si `/sys/class/power_supply` contiene dispositivos tipo `BAT*`. | Comportamiento esperado en PCs de escritorio o VMs. El monitor asume alimentación continua y no emite errores. |
| **Base de datos bloqueada / `database is locked`** | Concurrencia indebida o interrupción abrupta de transacciones SQLite. | Comprobar si existe `events.db-wal` o si hay procesos huérfanos: `pgrep -a python`. | `BackgroundDatabase` utiliza modo WAL y una cola de escritura serializada en hilo único. Si ocurrió un crash del sistema, detener el agente (`narrator stop`) y reiniciar. |
| **El monitor no narra ningún evento** | Umbral de severidad muy alto, cooldown activo o sistema en reposo absoluto. | Ejecutar con modo demo: `narrator start -f --demo` (usa umbral de CPU del 0.1%). | Si el sistema está en reposo (< 5% CPU), no se generan eventos para evitar spam. Provoca una carga temporal ejecutando en otra terminal: `stress --cpu 2 --timeout 5s`. |
| **Error de permisos al instalar el servicio systemd** | Se intentó instalar el servicio con `sudo` en lugar de usuario regular. | Verificar el comando ejecutado. El servicio de usuario no debe correr como `root`. | Ejecutar estrictamente como tu usuario habitual: `narrator service install`. |

---

## 3. Diagnóstico de Audio: Cascada de Motores

Para aislar si el problema radica en la generación de audio o en la reproducción física:

1. **Probar el reproductor físico del sistema:**
   ```bash
   aplay /usr/share/sounds/alsa/Front_Center.wav
   ```
   Si no emite sonido, el problema es la configuración del servidor de sonido (ALSA / PulseAudio / PipeWire / WSLg).
2. **Probar el sintetizador de respaldo `espeak-ng`:**
   ```bash
   espeak-ng -v es-la "Prueba de síntesis de voz en Ubuntu"
   ```
3. **Probar el modelo Piper TTS:**
   ```bash
   echo "Prueba con voz neuronal de Piper" | piper --model /ruta/al/modelo.onnx --output-raw | aplay -r 22050 -f S16_LE -t raw -
   ```

---

## 4. Diagnóstico de Conectividad con Gemini

Para verificar si tu clave de Gemini y la conexión a la API funcionan de forma aislada sin levantar los recolectores del sistema:
```bash
python scripts/test_analysis.py
```
Si la prueba tiene éxito, verás en pantalla un informe estructurado con el análisis generado por Gemini. Si la prueba falla por red o cuota, el script indicará la causa exacta del error (ej. `403 Forbidden` por clave inválida o `DeadlineExceeded` por timeout de red).
