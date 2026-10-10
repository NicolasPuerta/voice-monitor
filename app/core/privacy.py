"""Sanitización de datos para proteger la privacidad antes de enviarlos a Gemini."""

import re
from pathlib import Path

# Expresiones regulares para detectar secretos y datos sensibles
URL_CREDENTIALS_RE = re.compile(r"(https?://)([^:\s]+):([^@\s]+)@")
BEARER_TOKEN_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9\-\._~\+/]+=*")
JWT_TOKEN_RE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
AWS_KEY_RE = re.compile(r"(AKIA[0-9A-Z]{16})")


class PrivacySanitizer:
    """Elimina informacin personal, secretos y paths innecesarios de los textos."""

    def __init__(self, home_dir: str | Path | None = None) -> None:
        if home_dir is None:
            self.home_dir = str(Path.home())
        else:
            self.home_dir = str(home_dir)
        self.home_dir = self.home_dir.rstrip("/")

    def sanitize_text(self, text: str | None) -> str | None:
        """Sanitiza un texto libre eliminando secretos y rutas personales."""
        if not text:
            return text

        # Redactar directorio home
        if self.home_dir and len(self.home_dir) > 2:
            text = text.replace(self.home_dir, "~")

        # Eliminar credenciales de URLs
        text = URL_CREDENTIALS_RE.sub(r"\1***:***@", text)

        # Eliminar tokens genricos (Bearer)
        text = BEARER_TOKEN_RE.sub(r"\1***", text)

        # Eliminar JWTs
        text = JWT_TOKEN_RE.sub(r"***JWT***", text)

        # Eliminar AWS Keys posibles
        text = AWS_KEY_RE.sub(r"***AWS_KEY***", text)

        return text

    def sanitize_dict(self, data: dict[str, str]) -> dict[str, str]:
        """Aplica la sanitizacin a todos los valores de un diccionario."""
        return {k: self.sanitize_text(v) or "" for k, v in data.items()}
