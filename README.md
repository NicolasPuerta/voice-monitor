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

Estructura inicial. Aún no están implementados el monitoreo, la
integración con Gemini ni el audio.

## Estructura

```
app/       Código fuente (punto de entrada: app/main.py)
tests/     Pruebas con pytest
scripts/   Utilidades de desarrollo
```

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
