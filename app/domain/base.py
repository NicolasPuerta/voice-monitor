"""Base y tipos comunes de los modelos de dominio."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class DomainModel(BaseModel):
    """Modelo base inmutable que rechaza campos desconocidos."""

    model_config = ConfigDict(frozen=True, extra="forbid")


Percent = Annotated[float, Field(ge=0, le=100)]
"""Porcentaje entre 0 y 100."""

NonNegativeFloat = Annotated[float, Field(ge=0)]
"""Número real mayor o igual que cero."""

NonNegativeInt = Annotated[int, Field(ge=0)]
"""Entero mayor o igual que cero."""
