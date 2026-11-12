#!/usr/bin/env bash
# Prueba de funcionamiento de punta a punta de Ubuntu Voice Monitor.
set -u
cd ~/Descargas/voice-monitor
N=.venv/bin/narrator
DATA=~/.local/share/ubuntu-voice-monitor
LOG=$DATA/narrator.log
paso() { echo; echo "=== [$(date +%T)] $* ==="; }

paso "0. Estado inicial"
$N stop >/dev/null 2>&1
: > "$LOG"
$N status 2>&1 | grep -E "Estado General|Gemini|Audio|Presión|systemd|journald" | head -8

paso "1. Arranque en segundo plano (con audio)"
$N start 2>&1
sleep 8
$N status 2>&1 | grep -E "Estado General|Sesión|Gemini|Audio|DND" | head -8

paso "2. Carga de CPU: 3 procesos durante 25 s"
for i in 1 2 3; do (timeout 25 python3 -c "while True: pass" &); done
sleep 35

paso "3. Caída de un servicio (systemd-run --user false)"
systemd-run --user --quiet --unit=vm-prueba-falla false
sleep 25

paso "4. Bucle de fallos: el mismo servicio cae otra vez"
systemctl --user reset-failed vm-prueba-falla.service 2>/dev/null
systemd-run --user --quiet --unit=vm-prueba-falla false
sleep 25
systemctl --user reset-failed vm-prueba-falla.service 2>/dev/null

paso "5. Pausa (DND): una carga de CPU no debe sonar"
$N pause 2>&1
sleep 6
for i in 1 2 3; do (timeout 20 python3 -c "while True: pass" &); done
sleep 28
$N resume 2>&1
sleep 6

paso "6. Detención"
$N stop 2>&1
sleep 2

paso "7. Log del monitor (narraciones, Gemini, audio, DND)"
grep -E "GEMINI|NARRACIÓN|DND|Audio|audio|piper|espeak|ERROR|WARNING|Traceback|Señal|cerrado" "$LOG" \
  | grep -v "Cargando modelo\|cargado exitosamente" | cut -c1-260

paso "8. Sesión y eventos guardados"
$N session 2>&1 | head -30

paso "9. Informe HTML"
$N report --format html -o "$DATA/informe_prueba.html" 2>&1 | tail -3

paso "10. Errores en stderr del proceso"
wc -c < "$DATA/narrator.stderr.log"
