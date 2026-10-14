# Guía de Instalación Paso a Paso de Ubuntu Voice Monitor

Esta guía describe cómo instalar, configurar y verificar **Ubuntu Voice Monitor** (`narrator`) desde cero en **Ubuntu 22.04 LTS (Jammy)**, **Ubuntu 24.04 LTS (Noble)**, **Debian 12 (Bookworm)** y **WSL2 (Windows Subsystem for Linux)**.

---

## 1. Requisitos Previos del Sistema

### 1.1 Versión de Python y Sistema Operativo
- **Python:** Versión **3.10 o superior** (verificar con `python3 --version`).
- **Sistema Operativo:**
  - Ubuntu 22.04 LTS o 24.04 LTS (Nativo o en máquina virtual).
  - Debian 12 (Bookworm).
  - WSL2 en Windows 10/11 (con WSLg para soporte de audio).
- **Herramientas de compilación y librerías del sistema:**
  - `git`, `pkg-config`, `gcc`.
  - Librerías de desarrollo de systemd y D-Bus: `libsystemd-dev`, `libdbus-1-dev`.
  - Soporte de audio: `alsa-utils`, `espeak-ng` (o `piper`).

Instalación de paquetes del sistema en Ubuntu/Debian:
```bash
sudo apt update && sudo apt install -y \
    git \
    python3 \
    python3-pip \
    python3-venv \
    gcc \
    pkg-config \
    libsystemd-dev \
    libdbus-1-dev \
    alsa-utils \
    espeak-ng
```

---

## 2. Instalación en Ubuntu Nativo o Debian 12

Debido a la especificación **PEP 668** (vigente en Ubuntu 24.04 y Debian 12 para evitar conflictos con paquetes del sistema), se ofrecen dos métodos de instalación aislados:

### Método A: Instalación con `pipx` (Recomendado para usuarios finales)
`pipx` aísla las librerías en un entorno privado y expone el ejecutable `narrator` directamente en tu `$PATH` (`~/.local/bin`):

```bash
# 1. Instalar pipx (si no se encuentra instalado)
sudo apt install -y pipx
pipx ensurepath

# 2. Clonar el repositorio
git clone https://github.com/usuario/ubuntu-voice-monitor.git
cd ubuntu-voice-monitor

# 3. Instalar con soporte para reportes (Jinja2 / WeasyPrint)
pipx install ".[reports]"

# 4. Validar la instalación
narrator --help
narrator status
```

---

### Método B: Instalación en Entorno Virtual `venv` (Para desarrollo y depuración)

```bash
# 1. Clonar el repositorio y acceder a él
git clone https://github.com/usuario/ubuntu-voice-monitor.git
cd ubuntu-voice-monitor

# 2. Verificar versión de Python (requiere >= 3.10)
python3 --version

# 3. Crear el entorno virtual .venv
python3 -m venv .venv

# 4. Activar el entorno virtual
source .venv/bin/activate

# 5. Actualizar pip a la última versión
pip install --upgrade pip

# 6. Instalar dependencias del proyecto, desarrollo y reportes
pip install -e ".[dev,reports]"

# 7. Validar que los comandos estén disponibles en el venv
narrator --help
```

---

## 3. Instalación Específica en WSL2 (Windows Subsystem for Linux)

WSL2 presenta particularidades de arquitectura debido a que corre en un hipervisor virtualizado:

### 3.1 Habilitación de systemd en WSL2
Para que el recolector de systemd y el servicio de usuario funcionen, systemd debe estar activo como PID 1:
```bash
# Editar /etc/wsl.conf dentro de WSL
sudo tee /etc/wsl.conf > /dev/null <<EOF
[boot]
systemd=true
EOF
```
Cierra WSL y, desde PowerShell de Windows, reinicia la máquina virtual:
```powershell
wsl --shutdown
```
Al volver a entrar a WSL (`wsl`), comprueba con:
```bash
ps -p 1 -o comm=
# Debe responder: systemd
```

### 3.2 Soporte de Audio en WSL2
- **Windows 11 o Windows 10 con WSLg:** PulseAudio expone el socket automáticamente en `/mnt/wslg/runtime-dir/pulse/native`. Puedes comprobar la salida física de sonido ejecutando:
  ```bash
  aplay /usr/share/sounds/alsa/Front_Center.wav
  ```
- **Sin WSLg:** Si el audio físico no está disponible en tu máquina, puedes ejecutar el monitor en modo texto/silencioso agregando la bandera `--no-audio`:
  ```bash
  narrator --no-audio start
  ```

---

## 4. Configuración Inicial del Archivo de Entorno (`.env`)

El monitor busca la configuración en `.env` (directorio del proyecto) o en `~/.config/ubuntu-voice-monitor/config.env`:

```bash
# Opción 1: En el directorio de trabajo
cp .env.example .env

# Opción 2: En la ruta XDG estándar para servicios
mkdir -p ~/.config/ubuntu-voice-monitor
cp .env.example ~/.config/ubuntu-voice-monitor/config.env
```

Edita el archivo `.env`:
```ini
# Para habilitar Gemini (opcional):
GEMINI_ENABLED=true
GEMINI_API_KEY=tu_clave_de_google_ai_studio
GEMINI_MODEL=gemini-2.5-flash

# Para utilizar voz neuronal Piper TTS (opcional):
NARRATION_PIPER_MODEL_PATH=/home/usuario/.local/share/piper/es_ES-davefx-medium.onnx
```

---

## 5. Validación y Ejecución de Pruebas

Para confirmar que todas las dependencias y módulos se integraron correctamente, corre la suite de pruebas del proyecto:

```bash
# Ejecutar la suite completa de pruebas (247 tests)
pytest

# Ejecutar con reporte de cobertura
pytest --cov=app --cov-report=term-missing

# Ejecutar linters de calidad
flake8 app tests scripts packaging
mypy app
pylint app --errors-only
```
Todas las pruebas se ejecutan sin requerir conexión a Internet ni hardware físico de sonido.
