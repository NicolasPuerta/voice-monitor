"""Configuración centralizada de la aplicación basada en Pydantic Settings.

La configuración se agrupa por responsabilidad. Cada grupo lee sus propias
variables de entorno (con su prefijo) y ``Settings`` los reúne en un único
objeto inmutable.
"""

from enum import Enum
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.logging import get_logger, normalize_log_level

logger = get_logger(__name__)


class AppEnv(str, Enum):
    """Entorno de ejecución de la aplicación."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class NarrationVerbosity(str, Enum):
    """Nivel de detalle de la narración."""

    MINIMAL = "minimal"
    NORMAL = "normal"
    VERBOSE = "verbose"


def _normalize_text(value: object) -> object:
    """Normaliza textos de entorno (sin espacios y en minúsculas).

    Args:
        value: Valor recibido desde el entorno.

    Returns:
        El texto normalizado, o el valor original si no es texto.
    """
    return value.strip().lower() if isinstance(value, str) else value


class _GroupSettings(BaseSettings):
    """Base común de los grupos de configuración."""

    model_config = SettingsConfigDict(
        extra="ignore",
        frozen=True,
        env_ignore_empty=True,
        env_file_encoding="utf-8",
    )


class AppSettings(_GroupSettings):
    """Configuración general de la aplicación (``APP_ENV``, ``LOG_LEVEL``)."""

    app_env: AppEnv = AppEnv.DEVELOPMENT
    """Entorno de ejecución."""

    log_level: str = "INFO"
    """Nivel de logging (DEBUG, INFO, WARNING, ERROR o CRITICAL)."""

    @field_validator("app_env", mode="before")
    @classmethod
    def _normalize_app_env(cls, value: object) -> object:
        """Acepta el entorno sin distinguir mayúsculas de minúsculas.

        Args:
            value: Valor recibido desde el entorno.

        Returns:
            El valor normalizado.
        """
        return _normalize_text(value)

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        """Valida y normaliza el nivel de logging.

        Args:
            value: Nivel de logging recibido.

        Returns:
            El nivel de logging en mayúsculas.

        Raises:
            ValueError: Si el nivel no está soportado.
        """
        return normalize_log_level(value)


class CollectorSettings(_GroupSettings):
    """Configuración de los collectors (variables ``COLLECTOR_*``)."""

    model_config = SettingsConfigDict(env_prefix="COLLECTOR_")

    interval_s: float = Field(default=5.0, ge=0.5, le=3600)
    """Segundos entre lecturas con la máquina conectada a la corriente."""

    battery_interval_s: float = Field(default=15.0, ge=0.5, le=3600)
    """Segundos entre lecturas cuando la máquina funciona con batería."""

    adaptive: bool = True
    """Si es verdadero, el intervalo se adapta a la actividad del sistema."""

    @model_validator(mode="after")
    def _validate_intervals(self) -> "CollectorSettings":
        """Valida que el intervalo en batería no sea menor que el normal.

        Returns:
            La propia configuración, si es válida.

        Raises:
            ValueError: Si el intervalo en batería es menor que el normal.
        """
        if self.battery_interval_s < self.interval_s:
            raise ValueError(
                "COLLECTOR_BATTERY_INTERVAL_S no puede ser menor que "
                "COLLECTOR_INTERVAL_S"
            )
        return self


class NarrationSettings(_GroupSettings):
    """Configuración de la narración (variables ``NARRATION_*``)."""

    model_config = SettingsConfigDict(env_prefix="NARRATION_")

    verbosity: NarrationVerbosity = NarrationVerbosity.NORMAL
    """Nivel de detalle de la narración."""

    min_gap_s: float = Field(default=10.0, ge=0)
    """Segundos mínimos entre dos narraciones consecutivas."""

    max_burst: int = Field(default=3, ge=1)
    """Máximo de narraciones seguidas antes de aplicar una pausa."""

    event_ttl_s: float = Field(default=60.0, gt=0)
    """Segundos de vigencia de un evento antes de descartarse sin narrar."""

    piper_model_path: str | None = None
    """Ruta opcional al modelo .onnx de Piper TTS."""

    @field_validator("verbosity", mode="before")
    @classmethod
    def _normalize_verbosity(cls, value: object) -> object:
        """Acepta la verbosidad sin distinguir mayúsculas de minúsculas.

        Args:
            value: Valor recibido desde el entorno.

        Returns:
            El valor normalizado.
        """
        return _normalize_text(value)

    @model_validator(mode="after")
    def _validate_ttl(self) -> "NarrationSettings":
        """Valida que un evento no expire antes de poder narrarse.

        Returns:
            La propia configuración, si es válida.

        Raises:
            ValueError: Si el TTL es menor que el espacio mínimo entre narraciones.
        """
        if self.event_ttl_s < self.min_gap_s:
            raise ValueError(
                "NARRATION_EVENT_TTL_S no puede ser menor que NARRATION_MIN_GAP_S"
            )
        return self


class GeminiSettings(_GroupSettings):
    """Configuración de Gemini (variables ``GEMINI_*``)."""

    model_config = SettingsConfigDict(env_prefix="GEMINI_")

    enabled: bool = False
    """Habilita el análisis con Gemini."""

    model: str = Field(default="gemini-2.5-flash", min_length=1)
    """Nombre del modelo de Gemini."""

    api_key: SecretStr | None = None
    """API key de Gemini; solo se lee del entorno y nunca se muestra en logs."""

    @model_validator(mode="after")
    def _validate_api_key(self) -> "GeminiSettings":
        """Valida que exista API key cuando Gemini está habilitado.

        Returns:
            La propia configuración, si es válida.

        Raises:
            ValueError: Si Gemini está habilitado y no hay API key.
        """
        if self.enabled and self.api_key is None:
            raise ValueError("GEMINI_API_KEY es obligatoria si GEMINI_ENABLED=true")
        return self


class StorageSettings(_GroupSettings):
    """Configuración del almacenamiento (variables ``STORAGE_*``)."""

    model_config = SettingsConfigDict(env_prefix="STORAGE_")

    db_path: Path = Path("~/.local/share/ubuntu-voice-monitor/events.db")
    """Ruta del archivo de base de datos local."""

    @field_validator("db_path")
    @classmethod
    def _expand_user(cls, value: Path) -> Path:
        """Expande ``~`` en la ruta de la base de datos.

        Args:
            value: Ruta recibida.

        Returns:
            La ruta con el directorio del usuario expandido.
        """
        return value.expanduser()


class PrivacySettings(_GroupSettings):
    """Configuración de privacidad (variables ``PRIVACY_*``)."""

    model_config = SettingsConfigDict(env_prefix="PRIVACY_")

    redact_home: bool = True
    """Si es verdadero, se oculta el directorio personal en rutas y textos."""


class DndSettings(_GroupSettings):
    """Configuración de No Molestar (variables ``DND_*``)."""

    model_config = SettingsConfigDict(env_prefix="DND_")

    enabled: bool = False
    """Si es verdadero, no se narra ningún evento."""


class Settings(BaseModel):
    """Configuración completa e inmutable de la aplicación."""

    model_config = ConfigDict(frozen=True)

    app: AppSettings = Field(default_factory=AppSettings)
    """Configuración general."""

    collector: CollectorSettings = Field(default_factory=CollectorSettings)
    """Configuración de los collectors."""

    narration: NarrationSettings = Field(default_factory=NarrationSettings)
    """Configuración de la narración."""

    gemini: GeminiSettings = Field(default_factory=GeminiSettings)
    """Configuración de Gemini."""

    storage: StorageSettings = Field(default_factory=StorageSettings)
    """Configuración del almacenamiento."""

    privacy: PrivacySettings = Field(default_factory=PrivacySettings)
    """Configuración de privacidad."""

    dnd: DndSettings = Field(default_factory=DndSettings)
    """Configuración de No Molestar."""

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Settings":
        """Carga la configuración desde el entorno y, opcionalmente, un ``.env``.

        Las variables de entorno tienen prioridad sobre el archivo.

        Args:
            env_file: Ruta de un archivo ``.env``. Si es ``None`` no se lee ninguno.

        Returns:
            La configuración validada.

        Raises:
            pydantic.ValidationError: Si algún valor es inválido (es una
                subclase de ``ValueError``).
        """
        settings = cls(
            app=AppSettings(_env_file=env_file),
            collector=CollectorSettings(_env_file=env_file),
            narration=NarrationSettings(_env_file=env_file),
            gemini=GeminiSettings(_env_file=env_file),
            storage=StorageSettings(_env_file=env_file),
            privacy=PrivacySettings(_env_file=env_file),
            dnd=DndSettings(_env_file=env_file),
        )
        logger.debug(
            "Configuración cargada (entorno=%s, nivel de log=%s, gemini=%s).",
            settings.app.app_env.value,
            settings.app.log_level,
            "habilitado" if settings.gemini.enabled else "deshabilitado",
        )
        return settings
