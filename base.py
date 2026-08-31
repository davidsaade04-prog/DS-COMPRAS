"""
Interfaz de adaptador de fuente (SEA-01/SEA-02 del Plan de Desarrollo).
Cada fuente real (MercadoLibre, Frávega, etc.) implementa esto en H3+.
Hoy solo existen los mocks; agregar una fuente real NO debería requerir
tocar SearchService ni el Normalizer.
"""

from __future__ import annotations
from abc import ABC, abstractmethod

from domain import SourceTier
from search import SearchCriteria


class SearchAdapter(ABC):
    source_name: str
    source_tier: SourceTier

    @abstractmethod
    def search(self, criteria: SearchCriteria) -> list[dict]:
        """Devuelve ofertas en el formato NATIVO de la fuente (sin normalizar).
        Debe levantar una excepción si la fuente falla (timeout, error, etc.);
        SearchService se encarga de capturarla."""
        ...
