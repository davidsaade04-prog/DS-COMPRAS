"""
Adaptador EXPERIMENTAL a Frávega, vía la API pública de búsqueda de VTEX
(la plataforma de e-commerce sobre la que corre fravega.com).
Documentación: https://developers.vtex.com/docs/api-reference/productsearch

Importante - a diferencia de MercadoLibreAdapter, esto NO se pudo probar
contra la URL real desde el entorno de desarrollo (sin salida a internet).
Es un intento genuino basado en la documentación pública de VTEX, no una
integración verificada en producción. Si Frávega migró a una arquitectura
más nueva (GraphQL/FastStore) este endpoint clásico puede no responder -
en ese caso, el diseño de SearchService ya tolera que esta fuente falle
sin romper el resto de la búsqueda (V2.1 §2).
"""

from __future__ import annotations
import httpx

from base import SearchAdapter
from domain import SourceTier
from search import SearchCriteria

_BASE_URL = "https://www.fravega.com/api/catalog_system/pub/products/search"


class FravegaAdapter(SearchAdapter):
    source_name = "fravega"
    source_tier = SourceTier.B_VERIFICADO

    def __init__(self, limit: int = 5, timeout: float = 8.0):
        self._limit = limit
        self._timeout = timeout

    def search(self, criteria: SearchCriteria) -> list[dict]:
        url = f"{_BASE_URL}/{criteria.categoria}"
        params = {"_from": 0, "_to": max(self._limit - 1, 0)}
        response = httpx.get(url, params=params, timeout=self._timeout)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
