"""Interfaz base de los collectors del sistema."""

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

CollectedT_co = TypeVar("CollectedT_co", covariant=True)


class Collector(ABC, Generic[CollectedT_co]):
    """Contrato común de los collectors.

    Un collector observa una fuente del sistema (procesos, recursos, etc.) y
    devuelve modelos del dominio. Es estrictamente de solo lectura: nunca
    modifica el estado del sistema.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre corto y estable del collector, útil para logs.

        Returns:
            El nombre del collector.
        """

    @abstractmethod
    def collect(self) -> CollectedT_co:
        """Realiza una lectura de la fuente observada.

        No debe lanzar excepciones por condiciones normales del sistema,
        como recursos que desaparecen o falta de permisos.

        Returns:
            Modelos del dominio con los datos recolectados.
        """
