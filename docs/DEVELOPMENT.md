# Guía para Desarrolladores y Contribución

Esta guía documenta los estándares de código, las convenciones de arquitectura y las instrucciones paso a paso para extender las capacidades de **Ubuntu Voice Monitor**.

---

## 1. Convenciones y Estándares de Código

- **Idioma:**
  - **Identificadores de código (clases, métodos, variables):** Inglés (ej. `NarrationPipeline`, `EventGrouper`, `process_snapshot`).
  - **Docstrings, comentarios de código, logs y mensajes de usuario:** Español formal y conciso.
  - **Prompts de Gemini y salidas narradas:** Español natural de tono no técnico.
- **Formato y Estilo:**
  - Longitud máxima de línea: **90 caracteres** (estrictamente verificado con `flake8` y `pylint`).
  - Formateo según PEP 8.
- **Tipado Estático:**
  - Tipado riguroso al 100% verificado con `mypy app` (`strict = true`). No se admiten tipos `Any` no controlados ni llamadas sin anotación de retorno.
- **Inmutabilidad del Dominio:**
  - Las entidades del dominio heredan de `DomainModel` (`BaseModel` con `frozen=True`). Las mutaciones controladas internas de ciclo de vida (ej. `score_result`, `decision`) se realizan mediante `object.__setattr__`.
- **Aislamiento de Pruebas:**
  - Ninguna prueba automatizada debe depender de conexión a Internet, claves de API externas ni hardware físico de sonido.

---

## 2. Cómo Añadir un Nuevo Recolector (Collector)

Todos los recolectores heredan de `Collector[T]` (`app.collectors.base.py`):

1. **Definir el modelo de instantánea en `app/domain/`:**
   ```python
   from app.domain.base import DomainModel

   class NetworkSnapshot(DomainModel):
       bytes_sent: int
       bytes_recv: int
   ```
2. **Implementar el colector en `app/collectors/network.py`:**
   ```python
   from app.collectors.base import Collector
   from app.collectors.health import SourceHealthManager
   from app.domain.network import NetworkSnapshot

   class NetworkCollector(Collector[NetworkSnapshot | None]):
       def __init__(self, health_manager: SourceHealthManager | None = None) -> None:
           self.health_manager = health_manager

       def collect(self) -> NetworkSnapshot | None:
           try:
               # Lectura no invasiva de métricas
               return NetworkSnapshot(bytes_sent=1000, bytes_recv=2000)
           except Exception as exc:
               if self.health_manager:
                   self.health_manager.record_failure("network", str(exc))
               return None
   ```
3. **Integrar el colector en `SystemContextBuilder` (`app/core/context.py`).**
4. **Agregar pruebas unitarias en `tests/collectors/`.**

---

## 3. Cómo Añadir un Nuevo Tipo de Evento

1. **Registrar el tipo en `app/domain/enums.py`:**
   ```python
   class EventType(str, Enum):
       # ...
       NETWORK_SATURATION = "network_saturation"
   ```
2. **Definir la regla de detección en `app/core/detector.py`:**
   ```python
   if ctx.network and ctx.network.bytes_recv > UMBRAL_BYTES:
       events.append(
           Event(
               event_type=EventType.NETWORK_SATURATION,
               severity=EventSeverity.HIGH,
               summary="Saturación de ancho de banda de red detectada",
               metadata=EventMetadata(metric_value=ctx.network.bytes_recv),
           )
       )
   ```
3. **Añadir pruebas en `tests/core/test_detector.py`.**

---

## 4. Cómo Añadir Entradas a la Base de Conocimientos

El catálogo de procesos conocidos reside en [`app/storage/knowledge_data.json`](file:///c:/Users/USUARIO/Desktop/Projects/voicemonitor/voice-monitor/app/storage/knowledge_data.json).

Para incorporar un nuevo proceso:
1. Agrega el objeto JSON con evidencia verificable (sin alucinaciones ni opiniones):
   ```json
   {
     "key": "name:nginx",
     "short_text": "Servidor web y proxy inverso de alto rendimiento.",
     "long_text": "Maneja conexiones HTTP concurrentes y balanceo de carga.",
     "category": "database_and_servers",
     "source": "curated",
     "confidence": "high",
     "version": 1
   }
   ```
2. Ejecuta la suite de almacenamiento para verificar que el conteo y la integridad del catálogo se mantengan:
   ```bash
   pytest tests/storage/test_db.py
   ```

---

## 5. Cómo Añadir un Motor de Síntesis de Voz (Audio Generator)

Todos los motores de audio implementan `AudioGenerator` (`app/core/audio/interface.py`):

1. **Crear el adaptador en `app/core/audio/adapters/`:**
   ```python
   from app.core.audio.interface import AudioGenerator
   from app.domain.audio import AudioData

   class CustomTTSGenerator(AudioGenerator):
       def __init__(self) -> None:
           pass

       def synthesize(self, text: str) -> AudioData | None:
           # Generar o invocar el motor de voz y retornar AudioData
           # Retornar None si el motor falla o no está disponible
           ...
   ```
2. **Integrar el adaptador en la cascada de fallbacks de `AudioQueueManager`.**
3. **Añadir pruebas unitarias mockeadas en `tests/core/test_audio.py`.**

---

## 6. Flujo de Trabajo para Nuevos Merge Requests (MRs)

Antes de abrir un MR, comprueba que todos los criterios de calidad se cumplan:

```bash
# 1. Comprobar estilo (longitud <= 90 caracteres y PEP 8)
flake8 app tests scripts packaging

# 2. Comprobar tipado estricto
mypy app

# 3. Comprobar errores críticos con pylint
pylint app --errors-only

# 4. Ejecutar todas las pruebas con cobertura
pytest --cov=app --cov-report=term-missing

# 5. Ejecutar benchmark de rendimiento
python scripts/benchmark.py --scenario idle --ticks 10
```
Un MR se considera aceptable si y solo si:
- Mantiene el 100% de las pruebas pasando.
- Mantiene 0 errores en `flake8`, `mypy` y `pylint`.
- No introduce llamadas shell modificadoras del sistema operativo (estricto solo lectura).
- No filtra secretos ni rutas personales a Gemini.
