"""
Adaptador real a MercadoLibre Argentina (reemplaza los mocks de H3).
API pública: https://api.mercadolibre.com/sites/MLA/search - no requiere
autenticación para búsquedas básicas.

Alcance honesto: hoy esta es la ÚNICA fuente real conectada. "Comparar
distintos comercios" acá significa comparar distintos VENDEDORES reales
dentro de MercadoLibre (que agrega miles de tiendas independientes y
oficiales en Argentina) - no significa comparar contra sitios como Frávega
o Musimundo, que no ofrecen API pública gratuita; conectarlos requeriría
scraping (más frágil, con riesgo de términos de servicio), fuera de
alcance por ahora.

No pude probar la llamada real a internet desde este entorno de
desarrollo (sin salida a internet) - la validación real la hace el
servidor en producción.
"""

from __future__ import annotations
import httpx

from base import SearchAdapter
from domain import SourceTier
from search import SearchCriteria

_BASE_URL = "https://api.mercadolibre.com/sites/MLA/search"


class MercadoLibreAdapter(SearchAdapter):
    source_name = "mercadolibre"
    source_tier = SourceTier.B_VERIFICADO  # comercio/proveedor verificado (V2.1 §9)

    def __init__(self, limit: int = 5, timeout: float = 8.0):
        self._limit = limit
        self._timeout = timeout

    def search(self, criteria: SearchCriteria) -> list[dict]:
        params = {"q": criteria.query or criteria.categoria, "limit": self._limit}
        if criteria.presupuesto_max is not None:
            params["price_max"] = str(criteria.presupuesto_max)
        # Cualquier error acá (timeout, 4xx, 5xx) se propaga como excepción;
        # SearchService ya sabe aislar una fuente caída sin tirar abajo el
        # resto de la búsqueda (V2.1 §2 - fallos parciales).
        response = httpx.get(_BASE_URL, params=params, timeout=self._timeout)
        response.raise_for_status()
        return response.json().get("results", [])
