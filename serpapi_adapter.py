"""
Adaptador a Google Shopping (Argentina) vía SerpApi.
Documentación: https://serpapi.com/google-shopping-api

A diferencia de MercadoLibre/Frávega/Tienda BNA (una tienda cada una), esto
agrega resultados de MUCHOS comercios argentinos de una sola búsqueda
(Cetrogar, Musimundo, etc. pueden aparecer acá si Google los indexa).

Requiere la variable de entorno SERPAPI_KEY. Si no está configurada, esta
fuente simplemente falla (SearchService ya aísla esto, V2.1 §2) y el resto
sigue funcionando.

Nota de costo: el plan gratis de SerpApi da 250 búsquedas/mes en total
(para TODA la cuenta, no por fuente). Para uso personal alcanza, pero no
escala a muchos usuarios simultáneos sin pasar a un plan pago.
"""

from __future__ import annotations
import os
import httpx

from base import SearchAdapter
from domain import SourceTier
from search import SearchCriteria

_BASE_URL = "https://serpapi.com/search.json"


class SerpApiShoppingAdapter(SearchAdapter):
    source_name = "google_shopping"
    source_tier = SourceTier.C_AGREGADOR  # agrega de muchos comercios, ninguno verificado en particular

    def __init__(self, limit: int = 5, timeout: float = 10.0):
        self._limit = limit
        self._timeout = timeout

    def search(self, criteria: SearchCriteria) -> list[dict]:
        api_key = os.environ.get("SERPAPI_KEY")
        if not api_key:
            raise RuntimeError("Falta SERPAPI_KEY. Configurala en Render > Environment.")

        params = {
            "engine": "google_shopping",
            "q": criteria.query or criteria.categoria,
            "gl": "ar",              # resultados de Argentina
            "hl": "es",              # en español
            "google_domain": "google.com.ar",
            "api_key": api_key,
        }
        response = httpx.get(_BASE_URL, params=params, timeout=self._timeout)
        response.raise_for_status()
        data = response.json()
        return (data.get("shopping_results") or [])[: self._limit]
